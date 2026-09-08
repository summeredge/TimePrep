import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from core.filter import (
    DEFAULT_PARAMS,
    EWM,
    FIRST_ORDER_LOWPASS,
    METHOD_LABELS,
    METHODS,
    MOVING_AVERAGE,
    NONE,
    filter_column,
)
from core.loader import load_file, to_datetime
from core.processor import ProcessConfig, VariableConfig, process_data, process_file
from core.resample import numeric_like_frame, resample


class CoreProcessingTests(unittest.TestCase):
    def test_process_data_builds_frame_without_creating_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            pd.DataFrame(
                {
                    "Time": pd.date_range("2026-09-01 10:00", periods=6, freq="min"),
                    "A": [1, 3, 2, 5, 4, 6],
                }
            ).to_csv(source, index=False)
            config = ProcessConfig(
                resample_rule="2min",
                variables={"A": VariableConfig(True, MOVING_AVERAGE, {"window": 3})},
            )

            result = process_data(source, config)

            self.assertIsNone(result.output_path)
            self.assertEqual(result.processed, ["A"])
            self.assertIn("A_raw", result.frame.columns)
            self.assertIn("A_filtered", result.frame.columns)
            self.assertFalse(list(root.glob("*_processed.csv")))

    def test_process_file_wrapper_still_exports_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            pd.DataFrame(
                {
                    "Time": pd.date_range("2026-09-01 10:00", periods=4, freq="min"),
                    "A": [1, 2, 3, 4],
                }
            ).to_csv(source, index=False)
            config = ProcessConfig(
                variables={"A": VariableConfig(True, EWM, {"alpha": 0.5})}
            )

            result = process_file(source, root / "output", config)

            self.assertIsNotNone(result.output_path)
            self.assertTrue(Path(result.output_path).is_file())
            self.assertEqual(result.output_path.name, "source_processed.csv")

    def test_gui_config_collection_passes_rule_selection_methods_and_params(self):
        from ui.app import App

        class Value:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        app = App.__new__(App)
        app.rule_var = Value("5min")
        app.rows = [
            {
                "name": "A",
                "enabled": Value(True),
                "method": Value(METHOD_LABELS[MOVING_AVERAGE]),
                "params": Value("window=3"),
            },
            {
                "name": "B",
                "enabled": Value(False),
                "method": Value(METHOD_LABELS[EWM]),
                "params": Value("alpha=0.4"),
            },
        ]

        config = App._collect_config(app)

        self.assertEqual(config.resample_rule, "5min")
        self.assertEqual(config.as_dict()["variables"], {
            "A": {"enabled": True, "method": MOVING_AVERAGE, "params": {"window": 3}},
            "B": {"enabled": False, "method": EWM, "params": {"alpha": 0.4}},
        })

    def test_csv_named_time_column_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            pd.DataFrame({"Time": ["2024-01-01 00:00", "2024-01-01 00:01"], "A": [1, 2]}).to_csv(
                path, index=False
            )

            result = load_file(path)

        self.assertEqual(result.time_column, "Time")
        self.assertIsInstance(result.frame.index, pd.DatetimeIndex)
        self.assertEqual(result.columns, ["A"])

    def test_first_column_is_used_when_it_contains_times(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            pd.DataFrame({"Recorded At": ["2024-01-01", "2024-01-02"], "A": [1, 2]}).to_csv(
                path, index=False
            )

            result = load_file(path)

        self.assertEqual(result.time_column, "Recorded At")
        self.assertEqual(result.rows, 2)

    def test_resample_sorts_and_averages_numeric_columns(self):
        index = pd.to_datetime(["2024-01-01 00:01:30", "2024-01-01 00:00:10", "2024-01-01 00:00:40"])
        frame = pd.DataFrame({"A": [3.0, 1.0, 2.0], "Text": ["c", "a", "b"]}, index=index)

        result = resample(frame, "1min")

        self.assertEqual(list(result.index), list(pd.to_datetime(["2024-01-01 00:00", "2024-01-01 00:01"])))
        np.testing.assert_allclose(result["A"].to_numpy(), [1.5, 3.0])
        self.assertNotIn("Text", result.columns)

    def test_numeric_like_columns_keep_bad_values_as_nan(self):
        frame = pd.DataFrame(
            {
                "TIC101": [85.1, 85.3, "Bad", 85.4],
                "Mode": ["AUTO", "AUTO", "AUTO", "MAN"],
            }
        )

        result = numeric_like_frame(frame)

        self.assertIn("TIC101", result.columns)
        self.assertNotIn("Mode", result.columns)
        self.assertTrue(pd.isna(result.loc[2, "TIC101"]))

    def test_scan_off_column_survives_resampling_as_nan(self):
        index = pd.date_range("2026-09-01 10:00", periods=4, freq="min")
        frame = pd.DataFrame({"TIC101": [85.1, 85.3, "Scan Off", 85.4]}, index=index)

        result = resample(frame, "1min")

        self.assertIn("TIC101", result.columns)
        self.assertTrue(pd.isna(result.loc[index[2], "TIC101"]))

    def test_mixed_datetime_formats_parse_and_invalid_time_is_dropped(self):
        values = pd.Series(
            [
                "2026-09-01 10:00:00",
                "2026/09/01 10:01",
                "2026-09-01T10:02:00",
                "not-a-time",
            ]
        )

        parsed = to_datetime(values)

        self.assertEqual(parsed.notna().tolist(), [True, True, True, False])
        self.assertEqual(parsed.iloc[1], pd.Timestamp("2026-09-01 10:01:00"))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.csv"
            pd.DataFrame({"Time": values, "A": [1, 2, 3, 4]}).to_csv(path, index=False)
            loaded = load_file(path)

        self.assertEqual(loaded.rows, 3)
        self.assertEqual(loaded.dropped_rows, 1)

    def test_numeric_like_column_processes_and_exports_raw_filtered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "industrial.csv"
            pd.DataFrame(
                {
                    "Time": pd.date_range("2026-09-01 10:00", periods=6, freq="min"),
                    "TIC101": [85.1, 85.3, "Bad", 85.4, 85.5, 85.6],
                    "Mode": ["AUTO", "AUTO", "AUTO", "MAN", "MAN", "MAN"],
                }
            ).to_csv(source, index=False)
            config = ProcessConfig(
                resample_rule="1min",
                variables={"TIC101": VariableConfig(True, EWM, {"alpha": 0.5})},
            )

            result = process_file(source, root / "output", config)
            exported = pd.read_csv(result.output_path)

        self.assertEqual(result.processed, ["TIC101"])
        self.assertEqual(list(exported.columns), ["Time", "TIC101_raw", "TIC101_filtered"])
        self.assertTrue(pd.isna(exported.loc[2, "TIC101_raw"]))
        self.assertTrue(pd.isna(exported.loc[2, "TIC101_filtered"]))

    def test_filter_methods_return_same_index_and_change_series(self):
        index = pd.date_range("2024-01-01", periods=40, freq="s")
        series = pd.Series(np.sin(np.linspace(0, 8, len(index))) + np.tile([0.0, 1.0], 20), index=index)

        moving_average = filter_column(series, MOVING_AVERAGE, {"window": 3})
        ema = filter_column(series, EWM, {"alpha": 0.5})
        lowpass = filter_column(series, FIRST_ORDER_LOWPASS, {"tau": "5s"})

        for filtered in (moving_average, ema, lowpass):
            self.assertEqual(list(filtered.index), list(series.index))
            self.assertEqual(len(filtered), len(series))
            self.assertTrue(np.isfinite(filtered.to_numpy()).all())
        self.assertFalse(np.allclose(moving_average.to_numpy(), series.to_numpy()))
        self.assertFalse(np.allclose(ema.to_numpy(), series.to_numpy()))
        self.assertFalse(np.allclose(lowpass.to_numpy(), series.to_numpy()))

    def test_filter_methods_are_fixed_and_ordered(self):
        self.assertEqual(METHODS, (NONE, MOVING_AVERAGE, FIRST_ORDER_LOWPASS, EWM))
        self.assertEqual(
            [METHOD_LABELS[key] for key in METHODS],
            ["无滤波", "移动平均", "一阶低通滤波", "指数移动平均"],
        )
        self.assertEqual(DEFAULT_PARAMS[FIRST_ORDER_LOWPASS], {"tau": "10min"})

    def test_first_order_lowpass_uses_fixed_time_step(self):
        index = pd.date_range("2024-01-01", periods=4, freq="min")
        series = pd.Series([0.0, 10.0, 10.0, 10.0], index=index)
        alpha = 1 - np.exp(-60 / 120)
        expected = [0.0]
        for _ in range(3):
            expected.append(expected[-1] + alpha * (10.0 - expected[-1]))

        result = filter_column(series, FIRST_ORDER_LOWPASS, {"tau": "2min"})

        np.testing.assert_allclose(result.to_numpy(), expected)

    def test_first_order_lowpass_uses_actual_time_deltas(self):
        index = pd.to_datetime(
            [
                "2024-01-01 00:00:00",
                "2024-01-01 00:01:00",
                "2024-01-01 00:03:00",
                "2024-01-01 00:06:00",
            ]
        )
        series = pd.Series([0.0, 10.0, 10.0, 10.0], index=index)
        expected = [0.0]
        for delta_seconds in (60, 120, 180):
            alpha = 1 - np.exp(-delta_seconds / 120)
            expected.append(expected[-1] + alpha * (10.0 - expected[-1]))

        result = filter_column(series, FIRST_ORDER_LOWPASS, {"tau": "2min"})

        np.testing.assert_allclose(result.to_numpy(), expected)

    def test_first_order_lowpass_accepts_time_units(self):
        index = pd.date_range("2024-01-01", periods=4, freq="min")
        series = pd.Series([0.0, 1.0, 1.0, 1.0], index=index)

        for tau in ("30s", "5min", "1h"):
            result = filter_column(series, FIRST_ORDER_LOWPASS, {"tau": tau})
            self.assertEqual(len(result), len(series))

    def test_first_order_lowpass_rejects_invalid_tau(self):
        index = pd.date_range("2024-01-01", periods=4, freq="min")
        series = pd.Series([0.0, 1.0, 1.0, 1.0], index=index)

        for tau in (0, -1, "not-a-duration"):
            with self.assertRaisesRegex(ValueError, "时间常数"):
                filter_column(series, FIRST_ORDER_LOWPASS, {"tau": tau})

    def test_first_order_lowpass_requires_datetime_index(self):
        series = pd.Series([0.0, 1.0, 1.0, 1.0])

        with self.assertRaisesRegex(ValueError, "一阶低通滤波需要时间索引"):
            filter_column(series, FIRST_ORDER_LOWPASS, {"tau": "1min"})

    def test_first_order_lowpass_restores_original_nan(self):
        index = pd.date_range("2024-01-01", periods=5, freq="min")
        series = pd.Series([0.0, np.nan, 10.0, 10.0, 10.0], index=index)
        alpha = 1 - np.exp(-60 / 60)
        interpolated = [0.0, 5.0, 10.0, 10.0, 10.0]
        expected = [interpolated[0]]
        for value in interpolated[1:]:
            expected.append(expected[-1] + alpha * (value - expected[-1]))

        result = filter_column(series, FIRST_ORDER_LOWPASS, {"tau": "1min"})

        self.assertTrue(pd.isna(result.iloc[1]))
        np.testing.assert_allclose(
            result.dropna().to_numpy(), [expected[0], expected[2], expected[3], expected[4]]
        )

    def test_ema_and_moving_average_results_remain_unchanged(self):
        index = pd.date_range("2024-01-01", periods=4, freq="min")
        series = pd.Series([1.0, 3.0, 2.0, 5.0], index=index)

        moving_average = filter_column(series, MOVING_AVERAGE, {"window": 3})
        ema = filter_column(series, EWM, {"alpha": 0.5})

        np.testing.assert_allclose(moving_average.to_numpy(), [1.0, 2.0, 2.0, 10 / 3])
        np.testing.assert_allclose(ema.to_numpy(), [1.0, 2.0, 2.0, 3.5])

    def test_process_file_filters_selected_columns_and_exports_raw_filtered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            original = (
                "Time,A,B\n"
                "2024-01-01 00:03:10,7,70\n"
                "2024-01-01 00:00:10,1,10\n"
                "2024-01-01 00:05:10,11,110\n"
                "2024-01-01 00:01:30,4,40\n"
                "2024-01-01 00:04:10,9,90\n"
                "2024-01-01 00:00:40,2,20\n"
                "2024-01-01 00:02:10,5,50\n"
                "2024-01-01 00:01:10,3,30\n"
            )
            source.write_text(original, encoding="utf-8")
            config = ProcessConfig(
                resample_rule="1min",
                variables={
                    "A": VariableConfig(True, MOVING_AVERAGE, {"window": 2}),
                    "B": VariableConfig(True, EWM, {"alpha": 0.5}),
                },
            )

            result = process_file(source, root / "output", config)
            exported = pd.read_csv(result.output_path)

            self.assertEqual(result.processed, ["A", "B"])
            self.assertEqual(
                list(exported.columns),
                ["Time", "A_raw", "A_filtered", "B_raw", "B_filtered"],
            )
            self.assertEqual(result.rows_out, 6)
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            np.testing.assert_allclose(exported["A_raw"], [1.5, 3.5, 5.0, 7.0, 9.0, 11.0])
            np.testing.assert_allclose(exported["B_raw"], [15.0, 35.0, 50.0, 70.0, 90.0, 110.0])
            np.testing.assert_allclose(exported["A_filtered"], [1.5, 2.5, 4.25, 6.0, 8.0, 10.0])
            np.testing.assert_allclose(
                exported["B_filtered"], [15.0, 25.0, 37.5, 53.75, 71.875, 90.9375]
            )

    def test_unselected_column_is_kept_without_filter_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            pd.DataFrame(
                {
                    "Timestamp": pd.date_range("2024-01-01", periods=4, freq="min"),
                    "A": [1, 2, 3, 4],
                    "B": [10, 20, 30, 40],
                    "Mode": ["AUTO", "AUTO", "MAN", "MAN"],
                }
            ).to_csv(source, index=False)
            result = process_file(
                source,
                root / "output",
                ProcessConfig(
                    variables={
                        "A": VariableConfig(True, EWM, {"alpha": 0.5}),
                        "B": VariableConfig(),
                        "Mode": VariableConfig(True, EWM, {"alpha": 0.5}),
                    }
                ),
            )

        self.assertEqual(result.processed, ["A"])
        self.assertEqual(list(result.frame["B"]), [10, 20, 30, 40])
        self.assertEqual(list(result.frame["Mode"]), ["AUTO", "AUTO", "MAN", "MAN"])
        self.assertNotIn("B_raw", result.frame.columns)
        self.assertNotIn("B_filtered", result.frame.columns)
        self.assertNotIn("Mode_raw", result.frame.columns)
        self.assertNotIn("Mode_filtered", result.frame.columns)


if __name__ == "__main__":
    unittest.main()
