"""Section-box manipulator hosted by Kit's viewport scene layer."""

from __future__ import annotations

from .manipulator import SectionBoxManipulator
from .manipulator_model import SectionBoxManipulatorModel
from .state import SectionBoxState


class SectionBoxViewportItem:
    categories = ("manipulator",)
    name = "SectionBox"
    visible = True

    def __init__(self, viewport_args: dict, state: SectionBoxState, on_destroy):
        self.viewport_api = viewport_args["viewport_api"]
        self.model = SectionBoxManipulatorModel(state)
        self.manipulator = SectionBoxManipulator(self.model, viewport_api=self.viewport_api)
        self._on_destroy = on_destroy

    def destroy(self):
        if self.manipulator is None:
            return
        self.manipulator.destroy()
        self.manipulator = None
        self.model.destroy()
        self.model = None
        self._on_destroy(self.viewport_api)
