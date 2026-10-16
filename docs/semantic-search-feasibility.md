# Local semantic search: feasibility review

Date: 2026-10-16. This review does not measure model inference or retrieval gains.
No model was downloaded or loaded; no coding-agent benchmark was restarted.

## Observed environment

The Mac reports Apple M5 Pro, 24 GB memory and 15 CPU cores. The default
interpreter is Python 3.14.7 with SQLite 3.53.4. Torch, Transformers,
Sentence Transformers, MLX and ONNX Runtime are absent from that interpreter.
An existing unrelated Python 3.13.2 tool environment also lacks the checked
inference packages; it should not be modified for this experiment.

The local Hugging Face cache contains paraphrase-multilingual-MiniLM-L12-v2,
including model.safetensors: 494,492,244 bytes across 11 snapshot files. Its
sentence-transformer configuration limits sequences to 128 tokens despite the
underlying BERT position limit of 512. Existing 24-line chunks can exceed this.
Cache presence does not establish a usable inference runtime.

Noninteractive SSH to Omarchy failed with Permission denied (publickey).
Remote hardware was not measured. Local memory makes a small-model smoke test
plausible, but peak memory, accelerator compatibility and latency are unverified.
Use a separate disposable environment and pin working dependencies/revisions.

## What problem should be tested first?

The two weak retrospective references are already at unique-file ranks 10 and
12 in the lexical candidate set. Reranking directly tests this ordering failure;
embeddings test the separate problem of missing semantically related candidates.
These references are not exclusive relevance labels, and historical keyword
bags omitted task context. See local-search-diagnosis.md for limitations.

Current search accepts at most 1000 query characters and uses the first 16
unique lexical terms. A semantic experiment must retain the full task text
separately, with explicit model-token limits and recorded truncation. Do not
feed the shortened keyword bag to the model and call that a full-task test.
Score stored passages before the final 12-line/1400-character display cut.
Freshness checks remain authoritative regardless of semantic score.

## Candidates and sources

- First candidate: [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B).
  The publisher lists Apache-2.0, 0.6B parameters, multilingual support and 32K
  context. It scores query/passage pairs; its score is not calibrated evidence
  that a file is correct. Follow its supported scoring template.
- Retrieval experiment if needed: [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B).
  The publisher lists Apache-2.0, multilingual/code retrieval, 32K context and
  up to 1024 embedding dimensions. Follow documented query instructions,
  last-token pooling and normalization. These capabilities are publisher
  claims, not observed performance on this project.
- Existing-cache control: [multilingual MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
  It produces 384-dimensional sentence/paragraph vectors. It can provide a
  lightweight control, but code relevance is unproven here and the local
  128-token configuration risks truncating useful evidence.
- Alternative reranker: [BGE reranker v2 m3](https://huggingface.co/BAAI/bge-reranker-v2-m3),
  multilingual and Apache-2.0. Do not download several models before testing one.
- [Jina reranker v2](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual)
  lists CC-BY-NC-4.0 for its weights, so it is not the default candidate for the
  intended commercial distribution.

## Bounded next experiment

Freeze a maximum of 20 queries and relevance evidence before running a model.
Use multiple real repositories, full behavioral requests in Italian and English,
exact symbol/path controls, documentation, SQL agent notes, stale notes and
requests whose answer is absent. Existing synthetic cases are regression checks,
not proof of general usefulness. Identify useful evidence passages, not merely
one file changed by a historical patch.

Compare A: current lexical search, and B: the identical candidates reranked.
For the first smoke test cap reranking at 20 distinct files with at most two
passages each (40 pairs), 1024 tokens per pair and batch size 1 initially.
Record dropped/truncated evidence and candidate coverage before interpreting
ranking scores. Use identical output budgets. Exact path/symbol controls should
retain the deterministic path; report them separately from behavioral queries.

Measure candidate Recall@20, MRR/nDCG for the first three results, cold loading,
warm latency, peak memory and output bytes. Stop on load failure or excessive
runtime; do not expand into coding-agent trials. A quality gain must extend
beyond the two known weak queries and avoid exact/freshness regressions. Choose
an acceptable latency budget before treating the result as product-ready.

Only if missing candidates are a material failure, compare C: lexical plus dense
retrieval. Merge ranks (for example reciprocal-rank fusion), not incompatible
raw BM25 and vector scores. Index source chunks and relevant SQL notes with
content hashes; recompute embeddings only for changed content. Stale notes
must remain labeled stale. Measure indexing and update costs separately.

A learned decision router is premature: there are no representative labeled
routing outcomes yet. Begin with deterministic exact-query handling and an
optional semantic path for behavioral requests. This does not require a longer
startup skill prompt: the search implementation can own the choice internally.

## Conclusion

A local experiment is technically plausible. There is no measured evidence yet
that embeddings or reranking save agent tokens, improve completion quality or
outperform the agent's ordinary search. The next useful measurement is a small
reranking comparison, not another broad benchmark or a production dependency.
