"""Chat channels module with plugin architecture."""

from teai_builder.channels.base import BaseChannel
from teai_builder.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
