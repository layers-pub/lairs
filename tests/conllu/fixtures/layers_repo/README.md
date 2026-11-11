# Records built by the Layers UD importer

Each `<name>.conllu` here is a CoNLL-U fixture from `layers-repo`
(`tests/fixtures/ud_roundtrip`), and `<name>.records.json` holds the records the
`layers-repo` UD importer builds from it, as an AT-URI to record-value mapping
in wire form (`$type` keys and explicit nulls). Only the collections a reader
needs are kept: corpus, membership, expression, segmentation, annotation layer,
and alignment.

They were built at `layers-repo` commit `d03554557f7ef9b12e87134f3cad779bf4c6bb34` with
`build_records` from `scripts/check_ud_roundtrip.py`. The shape they follow is
stated in `docs/ud-reader-contract.md` of that repository.

`tests/conllu/test_reader.py` requires `lairs.conllu.sentences` to rebuild each
`.conllu` file byte for byte from its records. When the importer's record shape
changes, rebuild these files and update the reader with them.
