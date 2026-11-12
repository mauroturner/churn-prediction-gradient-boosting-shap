-- The candidates of the grid and their log loss on V1 (plan, section 19; D25, D26). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).

DROP TABLE IF EXISTS star_fact_selection;

CREATE TABLE star_fact_selection AS
SELECT feature_set, learning_rate, max_leaf_nodes, min_samples_leaf, log_loss_v1, chosen FROM ref_selection
ORDER BY feature_set, learning_rate, max_leaf_nodes, min_samples_leaf;
