"""Pydantic response models for dictionary lookup."""

from __future__ import annotations

from pydantic import BaseModel


class DictionaryExampleOut(BaseModel):
    text: str
    translation: str | None


class DictionarySenseOut(BaseModel):
    sense_index: int
    translation: str
    usage_note: str | None
    examples: list[DictionaryExampleOut]


class DictionaryEntryOut(BaseModel):
    headword: str
    part_of_speech: str | None
    senses: list[DictionarySenseOut]


class AttributionOut(BaseModel):
    source: str
    license: str
    url: str


class ExternalLinkOut(BaseModel):
    name: str
    url: str


class DictionaryLookupResponse(BaseModel):
    entries: list[DictionaryEntryOut]
    attribution: AttributionOut
    external_links: list[ExternalLinkOut]
