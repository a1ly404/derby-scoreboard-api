import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main
from client import ScoreboardClient


def test_create_app():
    """Test that create_app creates a FastAPI application with correct configuration."""
    app = main.create_app(scoreboard_host="testhost", scoreboard_port=9999)
    
    # Check that app has a scoreboard client configured
    assert hasattr(app.state, "scoreboard_client")
    assert isinstance(app.state.scoreboard_client, ScoreboardClient)
    assert app.state.scoreboard_client.host == "testhost"
    assert app.state.scoreboard_client.port == 9999


def test_create_app_defaults():
    """Test create_app with default parameters."""
    app = main.create_app()
    
    assert app.state.scoreboard_client.host == "localhost"  
    assert app.state.scoreboard_client.port == 8000


def test_parse_args():
    """Test argument parsing function."""
    with patch('sys.argv', ['main.py', '--scoreboard-host', 'custom-host', '--port', '3000']):
        args = main.parse_args()
        assert args.scoreboard_host == 'custom-host' 
        assert args.port == 3000
        assert args.scoreboard_port == 8000  # default
        assert args.host == '0.0.0.0'  # default


def test_parse_args_all_options():
    """Test argument parsing with all options."""
    test_argv = [
        'main.py',
        '--scoreboard-host', 'sb-host',
        '--scoreboard-port', '9000', 
        '--host', '127.0.0.1',
        '--port', '5555'
    ]
    with patch('sys.argv', test_argv):
        args = main.parse_args()
        assert args.scoreboard_host == 'sb-host'
        assert args.scoreboard_port == 9000
        assert args.host == '127.0.0.1'
        assert args.port == 5555