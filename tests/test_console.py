"""Tests for the headless console stream."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from reachy_mini.media.media_manager import MediaBackend
from reachy_mini_conversation_app.console import LocalStream


def test_clear_audio_queue_uses_clear_player_for_local() -> None:
    """LOCAL backend (GStreamer-based local audio) should use the lower-level player flush."""
    handler = MagicMock()
    audio = SimpleNamespace(
        clear_player=MagicMock(),
        clear_output_buffer=MagicMock(),
    )
    robot = SimpleNamespace(media=SimpleNamespace(audio=audio, backend=MediaBackend.LOCAL))
    stream = LocalStream(handler, robot)

    stream.clear_audio_queue()

    audio.clear_player.assert_called_once()
    audio.clear_output_buffer.assert_not_called()
    assert isinstance(handler.output_queue, asyncio.Queue)
    assert handler.output_queue.empty()


def test_clear_audio_queue_uses_output_buffer_for_webrtc() -> None:
    """WebRTC backend should flush queued playback via the output buffer API."""
    handler = MagicMock()
    audio = SimpleNamespace(
        clear_player=MagicMock(),
        clear_output_buffer=MagicMock(),
    )
    robot = SimpleNamespace(media=SimpleNamespace(audio=audio, backend=MediaBackend.WEBRTC))
    stream = LocalStream(handler, robot)

    stream.clear_audio_queue()

    audio.clear_output_buffer.assert_called_once()
    audio.clear_player.assert_not_called()
    assert isinstance(handler.output_queue, asyncio.Queue)
    assert handler.output_queue.empty()
