import os
def get_project_root():
    current_file=os.path.abspath(__file__)
    current_dir=os.path.dirname(current_file)
    project_root=os.path.dirname(current_dir)
    return project_root

def get_abs_path(path):
    project_root=get_project_root()
    return os.path.join(project_root,path)

