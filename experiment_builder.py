import os
from overrides import FORCED_ENGINE_SETTINGS, patch_modelparameters

# Definieer per experiment de cascade van mogelijke configuraties en interne paden.
# Zet de nieuwste/meest waarschijnlijke structuur altijd bovenaan.
EXPERIMENT_DEFINITIONS = [
    {
        "title": "Experiment 1: BaseData Run 1",
        "short_name": "Gen_Base_1",
        "cascades": [
            {
                "cfg_path": "cfg/main.dms",
                "result_node": "/WriteBaseData/Generate_Run1" 
            }
        ]
    },
    {
        "title": "Experiment 2: BaseData Run 2",
        "short_name": "Gen_Base_2",
        "cascades": [
            {
                "cfg_path": "cfg/main.dms",
                "result_node": "/WriteBaseData/Generate_Run2" 
            }
        ]
    },
    {
        "title": "Experiment 3: VariantData Run 1",
        "short_name": "Gen_Var_1",
        "cascades": [
            {
                # De nieuwe structuur (met BAU tussenlaag)
                "cfg_path": "cfg/main.dms",
                "result_node": "/WriteVariantData/per_Variant/BAU/Generate_Run1" 
            },
            {
                # De oude structuur (directe aanroep)
                "cfg_path": "cfg/main.dms",
                "result_node": "/WriteVariantData/Generate_Run1" 
            }
        ]
    }
    # Hier kun je in de toekomst makkelijk nieuwe experimenten toevoegen
]


def get_experiment_names():
    """Geeft de lijst met experiment-titels door aan de wizard interface."""
    return [exp["title"] for exp in EXPERIMENT_DEFINITIONS]

def get_valid_experiment_config(local_repo_path, cascades):
    """
    Controleert welke configuratie in de cascade fysiek bestaat in de huidige commit.
    Retourneert het pad en de bijbehorende result_node.
    """
    for cascade in cascades:
        full_path = os.path.join(local_repo_path, cascade["cfg_path"])
        if os.path.exists(full_path):
            return cascade["cfg_path"], cascade["result_node"]
            
    raise FileNotFoundError(f"Geen geldige configuratie gevonden in de cascade voor {local_repo_path}")

def build_all_experiments(regression_mod, geodms_paths, config, result_paths, mt_args, local_repo_path):
    
    # 1. Genereer de mapnaam EERST, terwijl de Git repository nog helemaal schoon is
    result_folder_name = regression_mod.get_result_folder_name(
        config["geodms_version"], geodms_paths, mt_args["MT1"], mt_args["MT2"], mt_args["MT3"], local_repo_path
    )

    # 2. Pas nu pas de modelparameters aan met onze robuuste Regex (maakt repo 'dirty')
    patch_modelparameters(local_repo_path)
    
    # 3. Zet de lokale opslagpaden klaar
    local_machine_parameters = {
        "SourceDataDir": config["source_data_dir"],
        "GEODMS_OVERRIDABLE_RSO_DataDir": config["source_data_dir"],
        "GEODMS_DIRECTORIES_LOCALDATADIR": config["test_dir"]
    }
    
    # 4. Injecteer de extra environment settings (RSL_VARIANT_NAME en AlleenEindjaar)
    local_machine_parameters.update(FORCED_ENGINE_SETTINGS)

    # Vertaal alles naar een environment string voor GeoDMS
    env_vars = regression_mod.get_full_regression_test_environment_string(
        local_machine_parameters, geodms_paths, {}, result_paths
    )

    result_folder = config["test_dir"]
    exps = []

    # 5. Bouw de commando's op basis van de cascade
    for exp in EXPERIMENT_DEFINITIONS:
        try:
            # Zoek uit of we de nieuwe of de oude structuur moeten gebruiken
            relative_cfg_path, result_node = get_valid_experiment_config(local_repo_path, exp["cascades"])
        except FileNotFoundError as e:
            print(f"[!] Waarschuwing: Overslaan van {exp['short_name']}. Detail: {e}")
            continue

        log_path = f"{result_folder}/{result_folder_name}/log/{exp['short_name']}.txt"
        cfg_path = f"{local_repo_path}/{relative_cfg_path}"
        
        # Construeer het run-commando
        cmd = f"{geodms_paths['GeoDmsRunPath']} /L{log_path} /{mt_args['MT1']} /{mt_args['MT2']} /{mt_args['MT3']} {cfg_path} @statistics {result_node}"

        regression_mod.add_exp(
            exps, 
            name=f"{result_folder_name}__{exp['short_name']}", 
            cmd=cmd, 
            exp_fldr=f"{result_folder}/{result_folder_name}", 
            env=env_vars, 
            log_fn=log_path
        )

    return exps, result_folder_name