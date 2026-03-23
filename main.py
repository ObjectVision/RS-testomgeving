import tkinter as tk
from tkinter import messagebox, filedialog
import json
import os
import sys
import importlib.util
import threading
import traceback  # Toegevoegd voor gedetailleerde foutmeldingen
from git_tools import clone_gitrepo_sha1
from experiment_builder import build_all_experiments, get_experiment_names

def load_geodms_modules(version: str):
    program_files = os.path.expandvars("%ProgramFiles%")
    base_path = f"{program_files}/ObjectVision/GeoDms{version}"
    
    profiler_path = f"{base_path}/profiler.py"
    regression_path = f"{base_path}/regression.py"
    
    spec_prof = importlib.util.spec_from_file_location("profiler", profiler_path)
    profiler_mod = importlib.util.module_from_spec(spec_prof)
    sys.modules["profiler"] = profiler_mod
    spec_prof.loader.exec_module(profiler_mod)
    
    spec_reg = importlib.util.spec_from_file_location("regression", regression_path)
    regression_mod = importlib.util.module_from_spec(spec_reg)
    sys.modules["regression"] = regression_mod
    spec_reg.loader.exec_module(regression_mod)
    
    regression_mod.profiler = profiler_mod
    
    geodms_paths = {
        "GeoDmsPlatform": "x64",
        "GeoDmsRunPath": f"\"{base_path}/GeoDmsRun.exe\"",
        "GeoDmsGuiQtPath": f"\"{base_path}/GeoDmsGuiQt.exe\""
    }
    
    return regression_mod, geodms_paths

def execute_test(sha_code, version, config, root, status_label):
    try:
        print(f"[*] Start clonen van repository (SHA: {sha_code})... Dit kan even duren.")
        local_repo_path = clone_gitrepo_sha1(config["git_repository_url"], sha_code, config["test_dir"])
        print(f"[+] Clonen voltooid. Map: {local_repo_path}")
        
        print("[*] GeoDMS modules laden...")
        regression, geodms_paths = load_geodms_modules(version)
        print("[+] Modules succesvol geladen.")
        
        result_paths = {
            "title": "RuimteScanner Test",
            "logo": "https://themasites.pbl.nl/o/zelfstandig-thuis-hoge-leeftijd/pbl-logo.png",
            "results_base_folder": config["test_dir"]
        }
        
        mt_args = {"MT1": "S1", "MT2": "S2", "MT3": "S3"}
        
        print("[*] Experimenten opbouwen en modelparameters patchen...")
        experiments, folder_name = build_all_experiments(regression, geodms_paths, config, result_paths, mt_args, local_repo_path)
        print(f"[+] {len(experiments)} experiment(en) succesvol klaargezet.")
        
        result_paths["results_folder"] = f"{config['test_dir']}/{folder_name}"
        result_paths["results_log_folder"] = f"{result_paths['results_folder']}/log"

        print("[*] GeoDMS berekeningen starten...")
        regression.run_experiments(experiments)
        
        print("[*] Testresultaten verzamelen en HTML rapport genereren...")
        regression.collect_and_generate_test_results(version, result_paths)
        print("[+] Voltooid!")
        
        root.after(0, lambda: messagebox.showinfo("Complete", "Test successfully finished!"))
        root.after(0, root.destroy)
        
    except Exception as e:
        print("\n!!! ER IS EEN FOUT OPGETREDEN !!!")
        traceback.print_exc()  # Print de exacte fout in de console
        
        # De tekst van de fout isoleren zodat Tkinter er niet mee in de knoop raakt
        err_msg = str(e)
        root.after(0, lambda msg=err_msg: messagebox.showerror("Error", f"An error occurred:\n{msg}"))
        root.after(0, root.destroy)

def centre_window(window, width, height):
    window.update_idletasks()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x_coordinate = int((screen_width / 2) - (width / 2))
    y_coordinate = int((screen_height / 2) - (height / 2))
    window.geometry(f"{width}x{height}+{x_coordinate}+{y_coordinate}")

def start_wizard():
    try:
        with open("config.json", "r") as f:
            config = json.load(f)
    except FileNotFoundError:
        print("The config.json file could not be found.")
        return

    root = tk.Tk()
    root.title("RuimteScanner Test Wizard")
    centre_window(root, 650, 550)

    def create_input_field(label_text, default_value):
        tk.Label(root, text=label_text).pack(pady=(10, 0))
        entry = tk.Entry(root, width=60)
        entry.insert(0, default_value)
        entry.pack(pady=(0, 5))
        return entry

    def create_directory_field(label_text, default_value):
        tk.Label(root, text=label_text).pack(pady=(10, 0))
        frame = tk.Frame(root)
        frame.pack(pady=(0, 5))
        entry = tk.Entry(frame, width=48)
        entry.insert(0, default_value)
        entry.pack(side=tk.LEFT, padx=(0, 5))
        def browse():
            directory = filedialog.askdirectory(initialdir=entry.get() or "C:/")
            if directory:
                entry.delete(0, tk.END)
                entry.insert(0, directory)
        btn = tk.Button(frame, text="Browse...", command=browse)
        btn.pack(side=tk.LEFT)
        return entry

    sha_entry = create_input_field("Git SHA1 code:", config.get("default_sha", ""))
    version_entry = create_input_field("GeoDMS Version:", config.get("geodms_version", "19.1.0"))
    source_data_entry = create_directory_field("Source Data Directory:", config.get("source_data_dir", ""))
    test_dir_entry = create_directory_field("Test Output Directory:", config.get("test_dir", ""))

    tk.Label(root, text="Experiments queued for execution:").pack(pady=(15, 0))
    experiment_listbox = tk.Listbox(root, height=4, width=58, bg="#f0f0f0")
    experiment_listbox.pack(pady=(0, 5))
    
    for exp_name in get_experiment_names():
        experiment_listbox.insert(tk.END, f" {exp_name}")

    status_label = tk.Label(root, text="", fg="blue")
    
    def on_run():
        sha_val = sha_entry.get().strip()
        if not sha_val:
            messagebox.showerror("Error", "Please provide a valid SHA1 code.")
            return
        if len(sha_val) > 7:
            sha_val = sha_val[:7]
            
        config["geodms_version"] = version_entry.get().strip()
        config["source_data_dir"] = source_data_entry.get().strip()
        config["test_dir"] = test_dir_entry.get().strip()
        
        run_button.config(state=tk.DISABLED)
        status_label.config(text="Cloning repository and computing... Please wait.")
        
        threading.Thread(target=execute_test, args=(sha_val, config["geodms_version"], config, root, status_label)).start()

    run_button = tk.Button(root, text="Start Test", command=on_run, bg="lightblue", font=("Arial", 10, "bold"))
    run_button.pack(pady=20)
    status_label.pack(pady=10)

    root.mainloop()

if __name__ == "__main__":
    start_wizard()