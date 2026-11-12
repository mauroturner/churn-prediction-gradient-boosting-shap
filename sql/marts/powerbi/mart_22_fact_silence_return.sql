-- The silences of the training that come back (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_silence_return;

CREATE TABLE star_fact_silence_return AS SELECT n, silences, return_share FROM eval_silence_return ORDER BY n;
