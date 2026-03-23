def get_experiment_names():
    """
    Returns a list of expected experiment names to display in the user interface.
    """
    return [
        "Experiment 1: Demo Baseline (A1 GE Discr)",
        "Experiment 2: Future Indicator Test",
        "Experiment 3: Data Comparison Run"
    ]

def build_all_experiments(regression_mod, geodms_paths, config, result_paths, mt_args, local_repo_path):
    """
    Defines and returns a list of all experiments to be run.
    """
    local_machine_parameters = {
        "SourceDataDir": config["source_data_dir"],
        "GEODMS_OVERRIDABLE_RSO_DataDir": config["source_data_dir"],
        "GEODMS_DIRECTORIES_LOCALDATADIR": config["local_data_dir"]
    }

    env_vars = regression_mod.get_full_regression_test_environment_string(
        local_machine_parameters, geodms_paths, {}, result_paths
    )

    result_folder_name = regression_mod.get_result_folder_name(
        config["geodms_version"], geodms_paths, mt_args["MT1"], mt_args["MT2"], mt_args["MT3"], local_repo_path
    )
    
    result_folder = config["test_dir"]
    exps = []

    # Experiment 1: Demo Baseline
    exp1_name = "A1_GE_Discr"
    log1_path = f"{result_folder}/{result_folder_name}/log/{exp1_name}.txt"
    demo_cfg = f"{local_repo_path}/lus_demo/cfg/demo.dms"
    
    cmd1 = f"{geodms_paths['GeoDmsRunPath']} /L{log1_path} /{mt_args['MT1']} /{mt_args['MT2']} /{mt_args['MT3']} {demo_cfg} @statistics Final_Results/A1_GE_Discr"

    regression_mod.add_exp(
        exps, 
        name=f"{result_folder_name}__{exp1_name}", 
        cmd=cmd1, 
        exp_fldr=f"{result_folder}/{result_folder_name}", 
        env=env_vars, 
        log_fn=log1_path
    )

    # Add Experiment 2, 3, 4 etc. right below this line using the exact same structure
    # ...

    return exps, result_folder_name