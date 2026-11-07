# text_normalize

Stable comparison keys for free text and organisation names. Standard library only.

```
text_normalize @ git+https://github.com/112345brian/bripe-job-search.git@<sha>#subdirectory=libs/text_normalize
```

```python
from text_normalize import normalize, normalize_org

normalize("R&D Lead (Remote)")            # "r d lead remote"   (kinds: text, space, fold, words, slug)
normalize_org("Foo Co., Ltd.", legal_suffixes={"co", "ltd", "inc"})   # "foo"
```

The legal-suffix set is passed in; the lib has no vocabulary data.
