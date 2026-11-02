"""Choose a pre-authorized duplicate policy without ambiguous overwrites."""
def choose_action(pages, policy):
    if policy not in ('skip','new','overwrite'):raise ValueError('无效重复处理方式')
    if not pages:return 'create',None
    if policy=='overwrite':
        if len(pages)!=1:raise ValueError('发现多条重复记录，请人工选择要覆盖的页面')
        return 'overwrite',pages[0]['id']
    return policy,None
