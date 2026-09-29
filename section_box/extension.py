"""Extension entry point — wires up all section-box subsystems.

Kit calls ``on_startup`` when the extension is enabled and ``on_shutdown``
when it is disabled or the application closes.
"""

from __future__ import annotations

from typing import Optional

import carb
import omni.ext
import omni.kit.app
import omni.kit.viewport.utility as vp_util
from omni.kit.viewport.registry import RegisterScene

from .clipping import ClipPlaneController
from .manipulator import SectionBoxManipulator
from .saved_positions import SavedPositionStore
from .state import SectionBoxState
from .toolbar import ToolbarButton
from .viewport_item import SectionBoxViewportItem
from .window import SectionBoxWindow

_runtime_state: SectionBoxState | None = None


def get_runtime_state() -> SectionBoxState | None:
    """Return the state owned by the running extension, if available."""
    return _runtime_state


class SectionBoxExtension(omni.ext.IExt):
    """Omniverse Kit extension that provides an interactive section box."""

    def __init__(self) -> None:
        super().__init__()
        self._state: Optional[SectionBoxState] = None
        self._clip_controller: Optional[ClipPlaneController] = None
        self._positions: Optional[SavedPositionStore] = None
        self._window: Optional[SectionBoxWindow] = None
        self._toolbar: Optional[ToolbarButton] = None
        self._manipulator: Optional[SectionBoxManipulator] = None
        self._scene_items: dict[int, SectionBoxViewportItem] = {}
        self._scene_registration = None
        self._update_sub = None

    # --- lifecycle -----------------------------------------------------------

    def on_startup(self, ext_id: str) -> None:
        global _runtime_state
        carb.log_info(f"[section.box] Starting up (ext_id={ext_id})")

        self._state = SectionBoxState()
        self._clip_controller = ClipPlaneController(self._state)
        self._positions = SavedPositionStore(self._state)
        self._window = SectionBoxWindow(self._state, self._positions)
        self._toolbar = ToolbarButton(self._state, self._window)

        self._setup_viewport_manipulator()
        self._update_sub = (
            omni.kit.app.get_app()
            .get_update_event_stream()
            .create_subscription_to_pop(self._on_update, name="section.box.viewport")
        )

        _runtime_state = self._state
        carb.log_info("[section.box] Ready")

    def on_shutdown(self) -> None:
        global _runtime_state
        carb.log_info("[section.box] Shutting down")

        if _runtime_state is self._state:
            _runtime_state = None

        # Tear down in reverse order.
        self._update_sub = None
        self._teardown_viewport_manipulator()

        if self._toolbar:
            self._toolbar.destroy()
            self._toolbar = None

        if self._window:
            self._window.destroy()
            self._window = None

        self._positions = None

        if self._clip_controller:
            self._clip_controller.destroy()
            self._clip_controller = None

        if self._state:
            self._state.destroy()
            self._state = None
        carb.log_info("[section.box] Shut down complete")

    # --- viewport manipulator setup ------------------------------------------

    def _setup_viewport_manipulator(self) -> None:
        """Add the grips to Kit's viewport scene, alongside camera and selection."""
        self._scene_registration = RegisterScene(self._create_viewport_item, "section.box.SectionBox")
        self._update_active_manipulator()

    def _create_viewport_item(self, viewport_args):
        item = SectionBoxViewportItem(viewport_args, self._state, self._on_viewport_item_destroyed)
        self._scene_items[item.viewport_api.id] = item
        return item

    def _on_viewport_item_destroyed(self, viewport_api):
        self._scene_items.pop(viewport_api.id, None)

    def _update_active_manipulator(self):
        viewport = vp_util.get_active_viewport_window(usd_context_name=None)
        item = self._scene_items.get(viewport.viewport_api.id) if viewport else None
        self._manipulator = item.manipulator if item else None

    def _teardown_viewport_manipulator(self) -> None:
        if self._scene_registration:
            self._scene_registration.destroy()
            self._scene_registration = None
        self._scene_items.clear()
        self._manipulator = None

    def _on_update(self, event) -> None:
        for item in self._scene_items.values():
            item.manipulator.sync_selection_guard()
        self._update_active_manipulator()
