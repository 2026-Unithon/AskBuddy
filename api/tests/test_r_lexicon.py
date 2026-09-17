import unittest
from pydantic import ValidationError
from app.reg.lexicon import LexiconEntry,matched_terms,validated_entries


class LexiconTest(unittest.TestCase):
    def test_alias_match_does_not_match_inside_other_word(self):
        entry=LexiconEntry(layer='STORE',term='라테',variants=('라떼',))
        self.assertEqual(matched_terms('라떼는 얼마?',(entry,)),('라테',))
        self.assertEqual(matched_terms('말차라떼',(entry,)),())

    def test_public_web_requires_provenance_and_usage_basis(self):
        with self.assertRaises(ValidationError):LexiconEntry(layer='COMMON',term='라테',variants=('라떼',),source='PUBLIC_WEB')

    def test_recipe_quantity_is_not_a_dictionary_entry(self):
        with self.assertRaises(ValidationError):LexiconEntry(layer='STORE',term='우유',variants=('225ml',))

    def test_ambiguous_alias_requires_review(self):
        with self.assertRaises(ValueError):validated_entries((
            LexiconEntry(layer='STORE',term='라테',variants=('별칭',)),
            LexiconEntry(layer='COMMON',term='커피',variants=('별칭',))))
