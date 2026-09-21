"""Operator-supplied reversible pseudonyms, kept out of the exchange package."""
import re


def checked_redactions(mapping):
    mapping = mapping or {}
    if not isinstance(mapping, dict) or any(not isinstance(k,str) or len(k.strip())<2
            or not isinstance(v,str) or not re.fullmatch(r'\[\[R_[0-9]{3,6}\]\]',v) for k,v in mapping.items()):
        raise ValueError('redactions require original strings and [[R_001]] tokens')
    if len(set(mapping.values())) != len(mapping) or any(token in key for key in mapping for token in mapping.values()):
        raise ValueError('redaction tokens must be unique and absent from originals')
    return mapping


def transform(value, mapping, *, restore=False):
    mapping = checked_redactions(mapping)
    replacements = {v:k for k,v in mapping.items()} if restore else mapping
    if isinstance(value, str) and replacements:
        # Single pass: replacements cannot trigger another replacement.
        pattern = '|'.join(re.escape(k) for k in sorted(replacements, key=len, reverse=True))
        return re.sub(pattern, lambda m: replacements[m.group()], value)
    if isinstance(value, list):return [transform(x,mapping,restore=restore) for x in value]
    if isinstance(value, dict):return {k:transform(v,mapping,restore=restore) for k,v in value.items()}
    return value
