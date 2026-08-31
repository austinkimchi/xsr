# Pinned English vocabulary

`scowl-american-english-2020.12.07.txt.gz` is a deterministic gzip (`gzip -n
-9`) of Debian `wamerican` 2020.12.07-2's `/usr/share/dict/american-english`.
The uncompressed snapshot has SHA-256
`9f513f1ceadb6a01c5485b7dbdfd5118dc66cd70b59cae2851292112d4066a32`.

The BM25 policy generator decodes the snapshot as UTF-8, lowercases it, filters
it through the supported ASCII word grammar, Porter2-stems it in userspace, and retains
only entries whose stems occur in the configured policy. This avoids both
benchmark-corpus dependence and speculative suffix generation.

The upstream notices and redistribution terms are preserved in
`SCOWL_COPYRIGHT.txt`.
