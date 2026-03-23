import os
import re

FORCED_ENGINE_SETTINGS = {
    "SectorAllocRegios": "Volledig",
    "InclusiefWindZon": "True",
    "InclusiefVerblijfsrecreatie": "True",
    "TestModus": "Actief"
}

FORCED_SECTOR_ALLOC_REGIO = """unit<UInt8> SectorAllocRegio := range(uint8, 0b, 5b) 
    , using = "/Classifications;/Classifications/actor;/Classifications/Modellering"
    {
        unit<Uint32> Elements := Range(uint32, 0, nrAttr * #.) 
        {
            attribute<String> Text: [
              'Wonen'              , 'NVM'                 ,  'TRUE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Wonen'              , 'Provincie'           , 'FALSE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Werken'             , 'NVM'                 ,  'TRUE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Werken'             , 'Provincie'           , 'FALSE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Verblijfsrecreatie' , 'Provincie'           ,  'TRUE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Zon'                , 'Provincie'           ,  'TRUE'       ,'Default_NrOfIters' ,'Default_NrOfIters'
             ,'Wind'               , 'Provincie'           ,  'TRUE'       ,'NrOfIters_Wind'    ,'NrOfIters_Wind'
            ];
        }
    }"""

def patch_modelparameters(local_repo_path):
    """
    Overschrijft de instellingen in het modelparameters bestand met de geforceerde teststandaard.
    """
    file_path = os.path.join(local_repo_path, "cfg", "main", "modelparameters.dms")
    
    if not os.path.exists(file_path):
        print(f"Waarschuwing: {file_path} niet gevonden. Patch overgeslagen.")
        return

    with open(file_path, 'r', encoding='utf8') as file:
        content = file.read()

    pattern = re.compile(r"unit<UInt8>\s+SectorAllocRegio\s*:=.*?\];\s*\}\s*\}", re.DOTALL | re.IGNORECASE)
    
    new_content = re.sub(pattern, lambda match: FORCED_SECTOR_ALLOC_REGIO, content)

    with open(file_path, 'w', encoding='utf8') as file:
        file.write(new_content)