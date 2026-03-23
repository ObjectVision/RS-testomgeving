import os
import re

FORCED_ENGINE_SETTINGS = {
    "RSL_VARIANT_NAME": "BAU",
    "AlleenEindjaar": "FALSE"
}

# Geef hier exact aan hoeveel actieve regels je in het array hieronder hebt staan
FORCED_SECTOR_COUNT = "4b" 

FORCED_TEXT_ARRAY = """
              'Wonen'              , 'NVM'                 ,  'TRUE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Wonen'              , 'Provincie'           , 'FALSE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Werken'             , 'NVM'                 ,  'TRUE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Werken'             , 'Provincie'           , 'FALSE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
"""

POSSIBLE_PARAM_PATHS = [
    "cfg/main/ModelParameters.dms", 
    "cfg/main/modelparameters.dms",
    "cfg/main/VariantParameters.dms"
]

def patch_modelparameters(local_repo_path):
    patch_applied = False

    # Regex 1: Zoekt specifiek naar de range definitie om het domein aan te passen
    pattern_domain = re.compile(r"(unit<UInt8>\s+SectorAllocRegio\s*:=\s*range\(\s*uint8\s*,\s*0b\s*,\s*)\d+b(\s*\))", re.IGNORECASE)
    
    # Regex 2: Zoekt de Text array op en pakt alles tussen [ en ];
    pattern_array = re.compile(r"(attribute<String>\s+Text\s*:\s*\[).*?(\];)", re.DOTALL | re.IGNORECASE)

    for rel_path in POSSIBLE_PARAM_PATHS:
        file_path = os.path.join(local_repo_path, rel_path)
        print(f"[*] Zoeken naar configuratiebestand: {file_path}")
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf8') as file:
                content = file.read()
            
            # Controleer of we beide specifieke onderdelen veilig kunnen vinden
            if pattern_domain.search(content) and pattern_array.search(content):
                
                # 1. Update de range
                content = pattern_domain.sub(rf"\g<1>{FORCED_SECTOR_COUNT}\g<2>", content)
                
                # 2. Update het array
                content = pattern_array.sub(lambda m: f"{m.group(1)}\n{FORCED_TEXT_ARRAY}            {m.group(2)}", content)
                
                with open(file_path, 'w', encoding='utf8') as file:
                    file.write(content)
                    
                print(f"[+] SectorAllocRegio array en range succesvol gepatcht in: {rel_path}")
                patch_applied = True
                break
            else:
                print(f"[!] Bestand {rel_path} gevonden, maar de interne 'Text' of 'range' structuur kon niet gematcht worden.")
                
    if not patch_applied:
        print("Waarschuwing: SectorAllocRegio kon niet worden overschreven. Patch overgeslagen.")