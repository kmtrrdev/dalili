"""Data providers behind the MCP servers.

Each provider has a demo implementation that works offline. Weather and FX
also have live implementations (Open-Meteo, Frankfurter) that need no API key.
Swapping in a commercial flight/hotel/places API means replacing one provider
class; the MCP tool contracts and everything above them stay the same.
"""
