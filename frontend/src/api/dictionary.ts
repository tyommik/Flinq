import { api } from './client'

export interface DictionarySense {
  sense_index: number
  translation: string
  usage_note: string | null
  examples: { text: string; translation: string | null }[]
}
export interface DictionaryEntry {
  headword: string
  part_of_speech: string | null
  senses: DictionarySense[]
}
export interface DictionaryLookup {
  entries: DictionaryEntry[]
  attribution: { source: string; license: string; url: string }
  external_links: { name: string; url: string }[]
}

export const dictionaryApi = {
  lookup: (lang: string, target: string, text: string) => {
    const q = new URLSearchParams({ lang, target, text })
    return api<DictionaryLookup>(`/api/dictionary/lookup?${q.toString()}`)
  },
}
