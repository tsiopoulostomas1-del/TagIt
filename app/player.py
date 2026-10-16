"""
Minimal audio player widget: play/pause, seek bar, elapsed/total time.
Uses QtMultimedia from PySide6 (no extra install needed).
"""
import os

from PySide6.QtCore import Qt, QUrl, QCoreApplication
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QLabel, QSlider, QSizePolicy
)


def _fmt_ms(ms: int) -> str:
    if ms <= 0:
        return "0:00"
    total_seconds = ms // 1000
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class PlaybackBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PlaybackBar")
        self.setFixedHeight(56)

        self._duration_ms = 0
        self._seeking = False

        # QtMultimedia backend
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.9)

        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        # --- Layout ---
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("PlayButton")
        self.btn_play.setFixedSize(38, 38)
        self.btn_play.clicked.connect(self.toggle_play)

        self.btn_stop = QPushButton("■")
        self.btn_stop.setObjectName("StopButton")
        self.btn_stop.setFixedSize(30, 30)
        self.btn_stop.clicked.connect(self.stop)

        self.time_current = QLabel("0:00")
        self.time_current.setObjectName("TimeLabel")
        self.time_current.setFixedWidth(48)
        self.time_current.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setObjectName("SeekSlider")
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._on_seek_start)
        self.slider.sliderReleased.connect(self._on_seek_end)
        self.slider.sliderMoved.connect(self._on_seek_move)
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.time_total = QLabel("0:00")
        self.time_total.setObjectName("TimeLabel")
        self.time_total.setFixedWidth(48)
        self.time_total.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout.addWidget(self.btn_play)
        layout.addWidget(self.time_current)
        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.time_total)
        layout.addWidget(self.btn_stop)

    # ------------------------------------------------------------- public API
    def load(self, path: str):
        """Load a new file and reset. Does not auto-play."""
        if not path or not os.path.isfile(path):
            self.clear()
            return
        try:
            self._player.stop()
        except Exception:
            pass
        self._player.setSource(QUrl.fromLocalFile(path))
        self._duration_ms = 0
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.time_current.setText("0:00")
        self.time_total.setText("0:00")

    def release(self):
        """
        Release any file handles Qt is holding on the current media.
        Windows keeps a lock on the file until the media source is
        fully cleared AND the event loop has processed the change.
        Call this before writing tags to the file.
        """
        try:
            self._player.stop()
        except Exception:
            pass
        try:
            self._player.setSource(QUrl())
        except Exception:
            pass
        # Force the event loop to actually close the backend handle
        QCoreApplication.processEvents()
        QCoreApplication.processEvents()

        # Reset UI
        self._duration_ms = 0
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.time_current.setText("0:00")
        self.time_total.setText("0:00")
        self.btn_play.setText("▶")

    def clear(self):
        """Same as release, but also meant to be called when hiding the bar."""
        self.release()

    def toggle_play(self):
        if self._player.source().isEmpty():
            return
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def stop(self):
        self._player.stop()

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    # ---------------------------------------------------------------- private
    def _on_position(self, pos: int):
        if not self._seeking:
            self.slider.setValue(pos)
        self.time_current.setText(_fmt_ms(pos))

    def _on_duration(self, dur: int):
        self._duration_ms = dur
        self.slider.setRange(0, dur)
        self.time_total.setText(_fmt_ms(dur))

    def _on_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self.btn_play.setText("❚❚")
        else:
            self.btn_play.setText("▶")

    def _on_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.slider.setValue(0)
            self.time_current.setText("0:00")
            self.btn_play.setText("▶")

    def _on_seek_start(self):
        self._seeking = True

    def _on_seek_end(self):
        self._seeking = False
        self._player.setPosition(self.slider.value())

    def _on_seek_move(self, value: int):
        self.time_current.setText(_fmt_ms(value))