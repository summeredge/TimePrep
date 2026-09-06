import unittest
from unittest import mock

from web import native_dialog


class NativeDialogTests(unittest.TestCase):
    def test_pick_keeps_dialog_topmost_and_restores_after_close(self):
        cases = (
            ("file", "askopenfilename", "C:\\data.csv", "C:\\data.csv"),
            ("dir", "askdirectory", "C:\\output", "C:\\output"),
        )

        for mode, dialog_name, selected, expected in cases:
            with self.subTest(mode=mode):
                calls = []

                class Root:
                    def attributes(self, name, value):
                        calls.append(("attributes", name, value))

                    def withdraw(self):
                        calls.append(("withdraw",))

                    def update(self):
                        calls.append(("update",))

                    def lift(self):
                        calls.append(("lift",))

                    def focus_force(self):
                        calls.append(("focus_force",))

                    def destroy(self):
                        calls.append(("destroy",))

                root = Root()
                dialog = mock.patch.object(
                    native_dialog.filedialog,
                    dialog_name,
                    side_effect=lambda *args, **kwargs: (
                        calls.append(("dialog",)) or selected
                    ),
                )
                with mock.patch.object(native_dialog.tk, "Tk", return_value=root), dialog:
                    result = native_dialog._pick(mode, "")

                self.assertEqual(result, {"path": expected})
                self.assertLess(
                    calls.index(("attributes", "-topmost", True)),
                    calls.index(("dialog",)),
                )
                self.assertEqual(
                    calls[-2:],
                    [("attributes", "-topmost", False), ("destroy",)],
                )


if __name__ == "__main__":
    unittest.main()
