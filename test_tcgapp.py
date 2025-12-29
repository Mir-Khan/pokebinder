import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure we can import the app from the current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tcgapp import TCGApp

class TestTCGApp(unittest.TestCase):
    def setUp(self):
        # Patch tkinter modules to prevent GUI creation during tests
        self.patcher_tk = patch('tcgapp.tk')
        self.patcher_ttk = patch('tcgapp.ttk')
        self.mock_tk = self.patcher_tk.start()
        self.mock_ttk = self.patcher_ttk.start()
        
        # Create a mock root for the TCGApp
        self.mock_root = MagicMock()
        
        # Instantiate the app with the mock root
        self.app = TCGApp(self.mock_root)
        
        # Mock internal methods/attributes to isolate load_set logic
        self.app.set_entry = MagicMock()
        self.app.refresh_binder = MagicMock()

    def tearDown(self):
        self.patcher_tk.stop()
        self.patcher_ttk.stop()

    @patch('tcgapp.requests.get')
    @patch('tcgapp.messagebox')
    def test_load_set_success(self, mock_mb, mock_get):
        """Test that load_set correctly fetches data and updates the app state."""
        # Setup the search term
        self.app.set_entry.get.return_value = "Base"
        
        # Mock the API response for the Set Search (Step 1)
        mock_set_response = MagicMock()
        mock_set_response.json.return_value = {
            'data': [{'id': 'base1', 'name': 'Base Set'}]
        }
        
        # Mock the API response for the Cards (Step 2)
        mock_cards_response = MagicMock()
        mock_cards_data = [
            {'id': 'c1', 'number': '1', 'images': {'small': 'url1'}},
            {'id': 'c2', 'number': '2', 'images': {'small': 'url2'}}
        ]
        mock_cards_response.json.return_value = {'data': mock_cards_data}
        
        # Configure requests.get to return the set response first, then the cards response
        mock_get.side_effect = [mock_set_response, mock_cards_response]

        # Execute the function
        self.app.load_set()

        # Assertions
        # 1. Check if requests.get was called twice (once for set, once for cards)
        self.assertEqual(mock_get.call_count, 2)
        
        # 2. Check if card data was stored
        self.assertEqual(len(self.app.card_data), 2)
        self.assertEqual(self.app.card_data[0]['id'], 'c1')
        
        # 3. Check if binder was refreshed
        self.app.refresh_binder.assert_called_once()
        
        # 4. Check success message
        mock_mb.showinfo.assert_called_with("Success", "Loaded set: Base Set (2 cards)")

    @patch('tcgapp.requests.get')
    @patch('tcgapp.messagebox')
    def test_load_set_not_found(self, mock_mb, mock_get):
        """Test that load_set handles cases where no set is found."""
        self.app.set_entry.get.return_value = "NonExistent"
        
        # Mock empty response
        mock_response = MagicMock()
        mock_response.json.return_value = {'data': []}
        mock_get.return_value = mock_response

        self.app.load_set()

        # Assert warning is shown and binder is NOT refreshed
        mock_mb.showwarning.assert_called_with("Not Found", "No sets found matching 'NonExistent'")
        self.app.refresh_binder.assert_not_called()

    @patch('tcgapp.requests.get')
    @patch('tcgapp.messagebox')
    def test_load_set_api_error(self, mock_mb, mock_get):
        """Test that load_set handles API exceptions gracefully."""
        self.app.set_entry.get.return_value = "Base"
        
        # Simulate an exception (e.g., no internet)
        mock_get.side_effect = Exception("Connection Error")

        self.app.load_set()

        # Assert error message is shown
        mock_mb.showerror.assert_called()
        self.assertIn("Search failed", mock_mb.showerror.call_args[0][1])

if __name__ == '__main__':
    unittest.main()