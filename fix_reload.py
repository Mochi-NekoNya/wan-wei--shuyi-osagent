import glob

files = glob.glob('backend/app/tests/test_*.py') + glob.glob('backend/app/tests/test_issue*.py')

for path in files:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    old_import = '    import backend.app.main as main_mod'
    if old_import not in content:
        continue
    
    count_import = content.count(old_import)
    count_reload = content.count('    importlib.reload(main_mod)')
    if count_import != count_reload:
        print(f'SKIP {path}: import count ({count_import}) != reload count ({count_reload})')
        continue
    
    new_import = '    import backend.app.app_runtime as runtime_mod\n    import backend.app.main as main_mod'
    content = content.replace(old_import, new_import)
    
    old_reload = '    importlib.reload(main_mod)'
    new_reload = '    importlib.reload(runtime_mod)\n    importlib.reload(main_mod)'
    content = content.replace(old_reload, new_reload)
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'FIXED {path}')

print('Done')
