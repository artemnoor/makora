import unittest
from unittest.mock import patch
from makora_core.source_verifier import verify_sources, fetch_public_text

class SourceVerificationTests(unittest.TestCase):
    def research(self,quote):
        return {'competitors':[{'status':'verified','sources':[{'url':'https://example.com/features','quote':quote}]}]}
    def test_exact_quote_is_required_and_content_is_checked(self):
        with patch('makora_core.source_verifier.fetch_public_text',return_value=('This product supports tag search and filters.','hash')) as fetch:
            result=verify_sources(self.research('supports tag search and filters'))
            self.assertEqual('passed',result[0]['status'])
            result=verify_sources(self.research('A fabricated feature not present anywhere'))
            self.assertEqual('failed',result[0]['status'])
            fetch.reset_mock()
            self.assertEqual('not_checked',verify_sources(self.research(''))[0]['status'])
            fetch.assert_not_called()
    def test_private_network_sources_are_not_requested(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]),patch('socket.create_connection') as connect:
            with self.assertRaises(ValueError):fetch_public_text('http://example.com/private')
            connect.assert_not_called()
    def test_too_many_sources_are_not_silently_verified(self):
        research={'competitors':[{'status':'verified','sources':[{'url':f'https://example.com/{i}','quote':'a long enough real quote'} for i in range(13)]}]}
        with patch('makora_core.source_verifier.fetch_public_text') as fetch:
            self.assertTrue(all(row['status']=='not_checked' for row in verify_sources(research)))
            fetch.assert_not_called()

    def test_different_quotes_on_same_url_have_distinct_evidence(self):
        research={'competitors':[{'status':'verified','sources':[{'url':'https://example.com','quote':'The real quoted feature on the page.'}]},
            {'status':'verified','sources':[{'url':'https://example.com','quote':'A fabricated quote on that same page.'}]}]}
        with patch('makora_core.source_verifier.fetch_public_text',return_value=('The real quoted feature on the page.','hash')):
            checks=verify_sources(research)
        self.assertEqual(['passed','failed'],[check['status'] for check in checks])
