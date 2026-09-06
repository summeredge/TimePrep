import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from core.filter import BUTTERWORTH, EWM, METHOD_LABELS, MOVING_AVERAGE, SAVGOL, filter_column
from core.loader import load_file
from core.processor import ProcessConfig, VariableConfig, process_file
from core.resample import resample


class CoreProcessingTests(unittest.TestCase):
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

    def test_filter_methods_return_same_index_and_change_series(self):
        index = pd.date_range("2024-01-01", periods=40, freq="s")
        series = pd.Series(np.sin(np.linspace(0, 8, len(index))) + np.tile([0.0, 1.0], 20), index=index)

        moving_average = filter_column(series, MOVING_AVERAGE, {"window": 3})
        ema = filter_column(series, EWM, {"alpha": 0.5})
        butterworth = filter_column(series, BUTTERWORTH, {"order": 2, "cutoff": 0.2})
        savgol = filter_column(series, SAVGOL, {"window": 5, "polyorder": 2})

        for filtered in (moving_average, ema, butterworth, savgol):
            self.assertEqual(list(filtered.index), list(series.index))
            self.assertEqual(len(filtered), len(series))
            self.assertTrue(np.isfinite(filtered.to_numpy()).all())
        self.assertFalse(np.allclose(moving_average.to_numpy(), series.to_numpy()))
        self.assertFalse(np.allclose(ema.to_numpy(), series.to_numpy()))
        self.assertFalse(np.allclose(butterworth.to_numpy(), series.to_numpy()))
        self.assertFalse(np.allclose(savgol.to_numpy(), series.to_numpy()))

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
                {"Timestamp": pd.date_range("2024-01-01", periods=4, freq="min"), "A": [1, 2, 3, 4], "B": [10, 20, 30, 40]}
            ).to_csv(source, index=False)
            result = process_file(
                source,
                root / "output",
                ProcessConfig(variables={"A": VariableConfig(True, EWM, {"alpha": 0.5}), "B": VariableConfig()}),
            )

        self.assertEqual(result.processed, ["A"])
        self.assertEqual(list(result.frame["B"]), [10, 20, 30, 40])
        self.assertNotIn("B_raw", result.frame.columns)
        self.assertNotIn("B_filtered", result.frame.columns)


if __name__ == "__main__":
    unittest.main()
