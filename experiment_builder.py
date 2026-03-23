import os
from overrides import FORCED_ENGINE_SETTINGS, patch_modelparameters

POSSIBLE_CFG_PATHS = [
    "cfg/main.dms",               
    "lus_demo/cfg/demo.dms",      
    "oud_model/run.dms"           
]

def get_valid_cfg_path(local_repo_path):
    """
    Loopt door de mogelijke paden en retourneert het eerste pad dat in deze commit bestaat.
    """
    for rel_path in POSSIBLE_CFG_PATHS:
        full_path = os.path.join(local_repo_path, rel_path)
        if os.path.exists(full_path):
            return rel_path
            
    raise FileNotFoundError(f"Geen geldig configuratiebestand gevonden in {local_repo_path}")

# Define all your experiments here. This is the ONLY place you need to make changes.
EXPERIMENT_DEFINITIONS = [
    {
        "title": "Generate_BaseData_Run_1",
        "short_name": "Gen_Base_1",
        "relative_cfg_path": "cfg/main.dms",
        "result_node": "/WriteBaseData/Generate_Run1"
    },
    {
        "title": "Generate_BaseData_Run_2",
        "short_name": "Gen_Base_2",
        "relative_cfg_path": "cfg/main.dms",
        "result_node": "/WriteBaseData/Generate_Run2"
    },
    {
        "title": "Generate_VariantData_Run_1",
        "short_name": "Gen_Var_1",
        "relative_cfg_path": "cfg/main.dms",
        "result_node": "/WriteVariantData/per_Variant/BAU/Generate_Run1"
    }
    # Add new experiments here as a new dictionary...
]

def get_experiment_names():
    return [exp["title"] for exp in EXPERIMENT_DEFINITIONS]

def build_all_experiments(regression_mod, geodms_paths, config, result_paths, mt_args, local_repo_path):
    
    # 1. Genereer de mapnaam EERST, terwijl de Git repository nog helemaal schoon is
    result_folder_name = regression_mod.get_result_folder_name(
        config["geodms_version"], geodms_paths, mt_args["MT1"], mt_args["MT2"], mt_args["MT3"], local_repo_path
    )

    # 2. Pas nu pas de modelparameters aan (dit maakt de repo 'dirty', maar dat maakt nu niet meer uit)
    patch_modelparameters(local_repo_path)
    
    # 3. Zoek het juiste pad naar het configuratiebestand
    relative_cfg_path = get_valid_cfg_path(local_repo_path)
    
    local_machine_parameters = {
        "SourceDataDir": config["source_data_dir"],
        "GEODMS_OVERRIDABLE_RSO_DataDir": config["source_data_dir"],
        "GEODMS_DIRECTORIES_LOCALDATADIR": config["test_dir"]
    }
    
    local_machine_parameters.update(FORCED_ENGINE_SETTINGS)

    env_vars = regression_mod.get_full_regression_test_environment_string(
        local_machine_parameters, geodms_paths, {}, result_paths
    )

    result_folder = config["test_dir"]
    exps = []

    for exp in EXPERIMENT_DEFINITIONS:
        log_path = f"{result_folder}/{result_folder_name}/log/{exp['short_name']}.txt"
        cfg_path = f"{local_repo_path}/{relative_cfg_path}"
        
        cmd = f"{geodms_paths['GeoDmsRunPath']} /L{log_path} /{mt_args['MT1']} /{mt_args['MT2']} /{mt_args['MT3']} {cfg_path} @statistics {exp['result_node']}"

        regression_mod.add_exp(
            exps, 
            name=f"{result_folder_name}__{exp['short_name']}", 
            cmd=cmd, 
            exp_fldr=f"{result_folder}/{result_folder_name}", 
            env=env_vars, 
            log_fn=log_path
        )

    return exps, result_folder_name