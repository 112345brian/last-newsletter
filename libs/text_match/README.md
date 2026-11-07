# text-match

Literal, whole-word text matching. No stemming, no fuzziness, no model — just
"does this piece of text say this term, as a whole word." Zero dependencies.

```python
from text_match import find_terms, normalize_term

terms = [normalize_term("brother")]
find_terms("my-brother said hello", terms)  # ["brother"]
find_terms("brotherhood", terms)  # []  -- not a whole-word match
```

`normalize_term` is the canonical form a term is stored/compared in: NFC,
whitespace collapsed, casefolded. `find_terms` matches already-normalized
terms against NFC-normalized text as whole words (not preceded or followed by
a letter, digit or underscore).

Originally written for a personal knowledge base, so a privacy keyword list
and an entity-alias list could never disagree about what "mentions" means —
factored out because the same question comes up anywhere text gets matched
against a vocabulary.
