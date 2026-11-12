-- The net benefit by break-even of the model and of B* (named by its method) (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_cost_sensitivity;

CREATE TABLE star_fact_cost_sensitivity AS
SELECT scope, break_even, CASE method WHEN 'b_star' THEN (SELECT b_star FROM ref_model) ELSE method END AS method_key, threshold, nb_per_1000,
       contact_share, seal_state
FROM eval_cost_sensitivity
ORDER BY scope, break_even, method_key, seal_state;
