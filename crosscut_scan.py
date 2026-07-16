#!/usr/bin/env python3
"""横切关注点扫描器 — 跨文件分析日志/异常/硬编码/循环导入/死代码/兼容性/类型注解"""
import ast, os, sys, re, json
from pathlib import Path
from collections import defaultdict

EXCLUDE_DIRS = {'__pycache__', '.git', 'build', 'build_mini_dist', 'tmp', 'backup', 'dist', 'tea_agent.egg-info', 'node_modules', '.tea_agent_run', '.tea_commands'}
EXCLUDE_PATTERNS = ['.bak', '.bak.']

def is_excluded(path):
    for p in Path(path).parts:
        if p in EXCLUDE_DIRS: return True
    fname = Path(path).name
    for pat in EXCLUDE_PATTERNS:
        if pat in fname: return True
    return False

def get_py_files(root_dir):
    py_files = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for f in filenames:
            if f.endswith('.py') and not is_excluded(os.path.join(dirpath, f)):
                py_files.append(os.path.join(dirpath, f))
    return py_files

def check_logging(filepath, source):
    issues = []
    lines = source.split('\n')
    has_logging = any('import logging' in l for l in lines)
    has_getlogger = any('logging.getLogger' in l or 'getLogger' in l for l in lines)
    has_logger = bool(re.search(r'\blogger\b', source, re.IGNORECASE))
    is_test = 'test_' in Path(filepath).stem
    print_count = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        code_part = line.split('#')[0] if '#' in line else line
        if 'print(' in code_part and re.search(r'\bprint\s*\(', code_part):
            print_count += 1
            if print_count <= 3:
                issues.append({'type':'logging_print','line':i,'msg':f"使用 print() 替代 logging: {stripped[:60]}",'severity':'warning' if not is_test else 'info'})
    if has_logging or has_logger:
        log_methods = ['debug','info','warning','error','critical','exception']
        for i, line in enumerate(lines, 1):
            for method in log_methods:
                if re.search(rf'\blogger\.{method}\s*\(\s*f["\']', line):
                    if 'extra=' not in line and '{' in line:
                        issues.append({'type':'logging_fstring','line':i,'msg':f"logger.{method}() 使用 f-string(非延迟求值): {line.strip()[:70]}",'severity':'suggestion'})
                    break
    return {'has_logging': has_logging or has_getlogger or has_logger, 'print_count': print_count, 'issues': issues}

def check_exceptions(filepath, source):
    issues = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {'issues': [{'type':'syntax_error','msg':'语法错误'}]}
    class ExcVisitor(ast.NodeVisitor):
        def visit_ExceptHandler(self, node):
            if node.type is None:
                issues.append({'type':'bare_except','line':node.lineno,'msg':f"裸 except: 没有指定异常类型",'severity':'error'})
            elif isinstance(node.type, ast.Name) and node.type.id == 'BaseException':
                issues.append({'type':'broad_except','line':node.lineno,'msg':f"捕获 BaseException (过于宽泛)",'severity':'error'})
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                issues.append({'type':'silent_except','line':node.lineno,'msg':f"异常被静默吞没 (except...pass)",'severity':'error'})
            self.generic_visit(node)
    ExcVisitor().visit(tree)
    return {'issues': issues}

def check_hardcoding(filepath, source):
    issues = []
    lines = source.split('\n')
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('\"\"\"') or stripped.startswith("'''"): continue
        for m in re.findall(r'["\']/[a-zA-Z0-9_/.]{3,}["\']', stripped):
            issues.append({'type':'hardcoded_path','line':i,'msg':f"硬编码 Unix 路径: {m[:50]}",'severity':'warning'})
        for m in re.findall(r'["\'](?:[A-Za-z]:\\\\[a-zA-Z0-9_\\\\ .]+)["\']', stripped):
            issues.append({'type':'hardcoded_path','line':i,'msg':f"硬编码 Windows 路径: {m[:50]}",'severity':'warning'})
        for ip in re.findall(r'["\'](\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})["\']', stripped):
            if ip not in ('127.0.0.1','0.0.0.0','255.255.255.255'):
                issues.append({'type':'hardcoded_ip','line':i,'msg':f"硬编码 IP 地址: {ip}",'severity':'warning'})
        if re.search(r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']+["\']', stripped, re.IGNORECASE):
            issues.append({'type':'hardcoded_secret','line':i,'msg':f"可能的硬编码密码: {stripped[:60]}",'severity':'error'})
        if re.search(r'(?:api_key|apikey)\s*=.*["\'][^"\']{8,}["\']', stripped, re.IGNORECASE):
            issues.append({'type':'hardcoded_secret','line':i,'msg':f"可能的硬编码 API Key: {stripped[:60]}",'severity':'error'})
    return {'issues': issues}

def check_circular_imports(py_files):
    module_map = {}
    for fp in py_files:
        try:
            with open(fp, 'r', encoding='utf-8') as f: source = f.read()
        except: continue
        rel_path = os.path.relpath(fp)
        rel_module = rel_path.replace(os.sep, '.')[:-3]
        if rel_module.endswith('.__init__'): rel_module = rel_module[:-9]
        imports = set()
        for m in re.finditer(r'from\s+(\S+)\s+import|import\s+(\S+)', source):
            imp = m.group(1) or m.group(2).split(' as ')[0].split(',')[0].strip()
            if imp.startswith('tea_agent'): imports.add(imp)
        if imports: module_map[rel_module] = imports
    circular = []
    checked = set()
    for module in list(module_map.keys()):
        if module in checked: continue
        path = []
        visited = set()
        def dfs(curr, path):
            nonlocal visited
            if curr in path:
                cs = path[path.index(curr):] + [curr]
                s = ' -> '.join(cs[:10])
                if s not in circular: circular.append(s)
                return
            if curr in checked: return
            path.append(curr)
            visited.add(curr)
            for dep in module_map.get(curr, set()):
                dfs(dep, path[:])
            path.pop()
            checked.add(curr)
        dfs(module, [])
    return {'circular_imports': circular}

def check_dead_code(filepath, source):
    issues = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {'issues': [{'type':'syntax_error','msg':'语法错误'}]}
    lines = source.split('\n')
    class DeadVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            for i, child in enumerate(node.body):
                if isinstance(child, ast.Return) and i+1 < len(node.body):
                    ns = node.body[i+1]
                    if not isinstance(ns, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        issues.append({'type':'dead_code','line':ns.lineno,'msg':f"return 后不可达代码 ({type(ns).__name__})",'severity':'warning'})
            self.generic_visit(node)
        def visit_If(self, node):
            if isinstance(node.test, ast.Constant) and not node.test.value:
                issues.append({'type':'dead_code','line':node.lineno,'msg':"永远不执行的 if 分支 (if False/None/0)",'severity':'warning'})
            self.generic_visit(node)
    DeadVisitor().visit(tree)
    import_lines = []
    for i, line in enumerate(lines, 1):
        m = re.match(r'^\s*(?:from\s+\S+\s+)?import\s+(.+)$', line)
        if m:
            for name in re.split(r'\s*,\s*', m.group(1)):
                name = name.strip()
                if ' as ' in name: name = name.split(' as ')[-1].strip()
                if 'TYPE_CHECKING' in line: continue
                import_lines.append((i, name))
    for i, name in import_lines:
        if name == '*' or len(name) <= 3: continue
        if source.count(name) <= 1 and name[0].isupper():
            issues.append({'type':'unused_import','line':i,'msg':f"可能未使用的导入: {name}",'severity':'info'})
    return {'issues': issues}

def check_py311_compat(filepath, source):
    issues = []
    lines = source.split('\n')
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('\"\"\"') or stripped.startswith("'''"): continue
        code = line.split('#')[0] if '#' in line else line
        if re.search(r'\bmatch\s+\S+\s*:', code):
            issues.append({'type':'py310_match','line':i,'msg':f"使用 match/case (3.10+): {stripped[:60]}",'severity':'info'})
        if re.match(r'\s*except\s*\*', stripped):
            issues.append({'type':'py311_except_star','line':i,'msg':f"使用 except* (3.11+): {stripped[:60]}",'severity':'info'})
        if re.match(r'\s*type\s+\w+\s*=', code):
            issues.append({'type':'py312_type_stmt','line':i,'msg':f"使用 type 语句 (3.12+): {stripped[:60]}",'severity':'info'})
    return {'issues': issues}

def check_type_annotations(filepath, source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {'func_count':0,'annotated_funcs':0,'args_total':0,'args_annotated':0,'return_annotated':0,'attr_total':0,'attr_annotated':0,'func_coverage_pct':100,'arg_coverage_pct':100,'attr_coverage_pct':100}
    class TVisitor(ast.NodeVisitor):
        def __init__(s):
            s.func_count=s.annotated_funcs=s.args_total=s.args_annotated=s.return_annotated=s.attr_total=s.attr_annotated=0
        def visit_FunctionDef(s, node):
            s.func_count+=1
            start = 1 if node.args.args and node.args.args[0].arg in ('self','cls') else 0
            for arg in node.args.args[start:]:
                s.args_total+=1
                if arg.annotation: s.args_annotated+=1
            if node.returns: s.annotated_funcs+=1; s.return_annotated+=1
            s.generic_visit(node)
        def visit_AsyncFunctionDef(s, node):
            s.func_count+=1
            for arg in node.args.args:
                s.args_total+=1
                if arg.annotation: s.args_annotated+=1
            if node.returns: s.annotated_funcs+=1; s.return_annotated+=1
            s.generic_visit(node)
        def visit_ClassDef(s, node):
            for child in node.body:
                if isinstance(child, ast.AnnAssign):
                    s.attr_total+=1
                    if child.annotation: s.attr_annotated+=1
            s.generic_visit(node)
    v = TVisitor()
    try: v.visit(tree)
    except: pass
    fc = round(v.annotated_funcs/v.func_count*100,1) if v.func_count else 100
    ac = round(v.args_annotated/v.args_total*100,1) if v.args_total else 100
    atc = round(v.attr_annotated/v.attr_total*100,1) if v.attr_total else 100
    return {'func_count':v.func_count,'annotated_funcs':v.annotated_funcs,'args_total':v.args_total,'args_annotated':v.args_annotated,'return_annotated':v.return_annotated,'attr_total':v.attr_total,'attr_annotated':v.attr_annotated,'func_coverage_pct':fc,'arg_coverage_pct':ac,'attr_coverage_pct':atc}

def scan_all(root_dir):
    py_files = get_py_files(root_dir)
    base = os.path.join(root_dir, 'tea_agent')
    core_files = [f for f in py_files if f.startswith(base) and not f.startswith(os.path.join(base,'toolkit')) and not f.startswith(os.path.join(base,'_gui')) and not f.startswith(os.path.join(base,'tests')) and not f.startswith(os.path.join(base,'demo')) and not f.startswith(os.path.join(base,'skills'))]
    toolkit_files = [f for f in py_files if f.startswith(os.path.join(base,'toolkit'))]
    gui_files = [f for f in py_files if f.startswith(os.path.join(base,'_gui'))]
    root_files = [f for f in py_files if os.path.dirname(f) == root_dir and f.endswith('.py')]
    
    results = {
        'summary':{'total_py_files':len(py_files),'scanned_files':len(core_files)+len(toolkit_files)+len(gui_files)+len(root_files),'core_files':len(core_files),'toolkit_files':len(toolkit_files),'gui_files':len(gui_files),'root_files':len(root_files)},
        'logging':{'issues':[]},'exceptions':{'issues':[]},'hardcoding':{'issues':[]},'circular_imports':[],'dead_code':{'issues':[]},'py311_compat':{'issues':[]},'type_coverage':{'files':[],'summary':{}}
    }
    
    for fp in core_files + toolkit_files + gui_files + root_files:
        try:
            with open(fp, 'r', encoding='utf-8') as f: source = f.read()
        except: continue
        rel = os.path.relpath(fp, root_dir)
        for iss in check_logging(fp,source)['issues']: iss['file']=rel; results['logging']['issues'].append(iss)
        for iss in check_exceptions(fp,source)['issues']: iss['file']=rel; results['exceptions']['issues'].append(iss)
        for iss in check_hardcoding(fp,source)['issues']: iss['file']=rel; results['hardcoding']['issues'].append(iss)
        for iss in check_dead_code(fp,source)['issues']: iss['file']=rel; results['dead_code']['issues'].append(iss)
        for iss in check_py311_compat(fp,source)['issues']: iss['file']=rel; results['py311_compat']['issues'].append(iss)
        tr = check_type_annotations(fp,source)
        results['type_coverage']['files'].append({'file':rel,'funcs':tr['func_count'],'annotated_funcs':tr['annotated_funcs'],'func_coverage':tr['func_coverage_pct'],'args_total':tr['args_total'],'args_annotated':tr['args_annotated'],'arg_coverage':tr['arg_coverage_pct'],'attrs':tr['attr_total'],'annotated_attrs':tr['attr_annotated'],'attr_coverage':tr['attr_coverage_pct']})
    
    circ = check_circular_imports(py_files)
    results['circular_imports'] = circ['circular_imports']
    
    tc = results['type_coverage']
    tf = sum(f['funcs'] for f in tc['files'])
    ta = sum(f['annotated_funcs'] for f in tc['files'])
    targ = sum(f['args_total'] for f in tc['files'])
    targa = sum(f['args_annotated'] for f in tc['files'])
    tatt = sum(f['attrs'] for f in tc['files'])
    tatta = sum(f['annotated_attrs'] for f in tc['files'])
    tc['summary'] = {'total_funcs':tf,'annotated_funcs':ta,'func_coverage_pct':round(ta/tf*100,1) if tf else 100,'total_args':targ,'annotated_args':targa,'arg_coverage_pct':round(targa/targ*100,1) if targ else 100,'total_class_attrs':tatt,'annotated_class_attrs':tatta,'attr_coverage_pct':round(tatta/tatt*100,1) if tatt else 100}
    
    return results

def format_report(results):
    s = results['summary']
    out = []
    out.append("="*72)
    out.append("   🔍 横切关注点审查报告 - Cross-Cutting Concerns Audit")
    out.append("="*72)
    out.append(f"   项目: tea_agent")
    out.append(f"   Python 文件总数: {s['total_py_files']}")
    out.append(f"   ├─ 核心源码: {s['core_files']} | 工具集: {s['toolkit_files']}")
    out.append(f"   ├─ GUI: {s['gui_files']}")
    out.append(f"   └─ 根目录脚本: {s['root_files']}")
    out.append(f"   本次扫描: {s['scanned_files']} 文件")
    out.append("")
    
    # 1. 日志
    out.append("─"*72)
    out.append("  📋 1. 日志规范 (Logging)")
    out.append("─"*72)
    pi = [i for i in results['logging']['issues'] if i['type']=='logging_print']
    fi = [i for i in results['logging']['issues'] if i['type']=='logging_fstring']
    if pi: out.append(f"   ⚠️  print() 替代 logging ({len(pi)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in pi]
    if fi: out.append(f"   💡 日志 f-string 非延迟求值 ({len(fi)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in fi]
    if not pi and not fi: out.append("   ✅ 日志使用规范良好")
    
    # 2. 异常
    out.append(""); out.append("─"*72)
    out.append("  📋 2. 异常处理模式 (Exception Handling)")
    out.append("─"*72)
    ei = results['exceptions']['issues']
    be = [i for i in ei if i['type']=='bare_except']
    se = [i for i in ei if i['type']=='silent_except']
    br = [i for i in ei if i['type']=='broad_except']
    if be: out.append(f"   ❌ 裸 except ({len(be)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in be]
    if se: out.append(f"   ❌ 静默吞没异常 ({len(se)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in se[:15]]
    if br: out.append(f"   ⚠️  过宽异常捕获 ({len(br)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in br]
    if not be and not se and not br: out.append("   ✅ 异常处理模式良好")
    
    # 3. 硬编码
    out.append(""); out.append("─"*72)
    out.append("  📋 3. 硬编码 (Hardcoded Values)")
    out.append("─"*72)
    hi = results['hardcoding']['issues']
    hs = [i for i in hi if i['type']=='hardcoded_secret']
    hp = [i for i in hi if i['type']=='hardcoded_path']
    hip = [i for i in hi if i['type']=='hardcoded_ip']
    if hs: out.append(f"   ❌ 敏感信息硬编码 ({len(hs)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in hs]
    if hp: out.append(f"   ⚠️  硬编码路径 ({len(hp)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in hp[:10]]
    if hip: out.append(f"   ⚠️  硬编码 IP ({len(hip)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in hip[:5]]
    if not hi: out.append("   ✅ 未发现硬编码问题")
    
    # 4. 循环导入
    out.append(""); out.append("─"*72)
    out.append("  📋 4. 循环导入 (Circular Imports)")
    out.append("─"*72)
    circ = results['circular_imports']
    if circ: out.append(f"   ❌ 检测到 {len(circ)} 个循环依赖链:"); [out.append(f"       └─ {c}") for c in circ]
    else: out.append("   ✅ 未检测到循环导入")
    
    # 5. 死代码
    out.append(""); out.append("─"*72)
    out.append("  📋 5. 死代码 (Dead Code)")
    out.append("─"*72)
    di = results['dead_code']['issues']
    dd = [i for i in di if i['type']=='dead_code']
    ui = [i for i in di if i['type']=='unused_import']
    if dd: out.append(f"   ⚠️  死代码 ({len(dd)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in dd]
    if ui: out.append(f"   💡 可能未使用的导入 ({len(ui)} 处):"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in ui[:15]]
    if not dd and not ui: out.append("   ✅ 未发现死代码")
    
    # 6. 兼容性
    out.append(""); out.append("─"*72)
    out.append("  📋 6. Python 3.11+ 兼容性")
    out.append("─"*72)
    ci = results['py311_compat']['issues']
    if ci: out.append(f"   💡 检测到 {len(ci)} 处版本特性使用:"); [out.append(f"       └─ {i['file']}:{i['line']}  {i['msg'][:75]}") for i in ci]
    else: out.append("   ✅ 全部兼容 Python 3.11+")
    
    # 7. 类型注解
    out.append(""); out.append("─"*72)
    out.append("  📋 7. 类型注解覆盖率 (Type Annotations)")
    out.append("─"*72)
    tcs = results['type_coverage']['summary']
    out.append(f"   📊 全局统计:")
    out.append(f"       ├─ 函数/方法: {tcs['total_funcs']} 个")
    out.append(f"       ├─ 已注解返回类型: {tcs['annotated_funcs']} 个")
    out.append(f"       ├─ 函数返回注解覆盖率: {tcs['func_coverage_pct']}%")
    out.append(f"       ├─ 参数总数: {tcs['total_args']} 个, 已注解: {tcs['annotated_args']} 个")
    out.append(f"       ├─ 参数注解覆盖率: {tcs['arg_coverage_pct']}%")
    out.append(f"       ├─ 类属性总数: {tcs['total_class_attrs']} 个, 已注解: {tcs['annotated_class_attrs']} 个")
    out.append(f"       └─ 类属性注解覆盖率: {tcs['attr_coverage_pct']}%")
    
    fs = sorted(results['type_coverage']['files'], key=lambda f: f['func_coverage'])
    lc = [f for f in fs if f['funcs']>0 and f['func_coverage']<50]
    if lc: out.append(f"\n   ⚠️  函数注解覆盖率 < 50% 的文件 ({len(lc)}):"); [out.append(f"       └─ {f['file']}: func={f['func_coverage']}%  arg={f['arg_coverage']}%") for f in lc[:12]]
    hc = [f for f in fs if f['funcs']>0 and f['func_coverage']>=80]
    if hc: out.append(f"\n   ✅ 函数注解覆盖率 >= 80% 的文件 ({len(hc)}):"); [out.append(f"       └─ {f['file']}: {f['func_coverage']}%  (args: {f['arg_coverage']}%)") for f in hc[:8]]
    
    out.append(""); out.append("="*72); out.append("   报告完毕"); out.append("="*72)
    return '\n'.join(out)

if __name__ == '__main__':
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    results = scan_all(root)
    print(format_report(results))
    rp = os.path.join(root, '.crosscut_report.json')
    with open(rp, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n详细 JSON 报告已保存到: {rp}")
