"""Playback in the viewer: the laser tracing a layer, and the layers as a flip-book."""

from __future__ import annotations

from . import theme


class PlaybackMixin:
    def _toggle_scan(self) -> None:
        if not self.result:
            return
        if self.view.playing():
            self.view.stop_scan()
        else:
            self.flipbook.stop()
            self._flip_state()
            self.view_switch.set_index(0)
            self.view.play_scan()

    def _scan_state(self, playing: bool) -> None:
        self.scan_button.setText("Stop laser" if playing else "Play laser")
        self.scan_button.setIcon(theme.icon("stop" if playing else "laser"))
        self.scan_button.setProperty("iconName", "stop" if playing else "laser")

    def _toggle_flipbook(self) -> None:
        if not self.result:
            return
        if self.flipbook.isActive():
            self.flipbook.stop()
        else:
            self.view.stop_scan()
            if self.slider.value() >= self.slider.maximum():
                self.slider.setValue(0)
            self.flipbook.start()
        self._flip_state()

    def _flip(self) -> None:
        if self.slider.value() >= self.slider.maximum():
            self.flipbook.stop()
            self._flip_state()
        else:
            self._step(1)

    def _flip_state(self) -> None:
        on = self.flipbook.isActive()
        self.flip_button.setText("Pause layers" if on else "Play layers")
        self.flip_button.setIcon(theme.icon("pause" if on else "film"))
        self.flip_button.setProperty("iconName", "pause" if on else "film")

    def _stop_playback(self) -> None:
        self.view.stop_scan()
        self.flipbook.stop()
        self._flip_state()
