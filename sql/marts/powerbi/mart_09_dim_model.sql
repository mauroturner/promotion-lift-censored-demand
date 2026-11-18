-- The frozen model of the launch, from the registry; the seal state says whether its configuration is the one of the seal file.
DROP TABLE IF EXISTS star_dim_model;

CREATE TABLE star_dim_model AS
SELECT model_version AS model_key, model_version, json_extract(recovery_json, '$.method') AS recovery_method, json_extract(recovery_json, '$.kappa') AS kappa,
       config_sha256, (SELECT launch_state FROM ref_seal) AS seal_state
FROM model_registry;
