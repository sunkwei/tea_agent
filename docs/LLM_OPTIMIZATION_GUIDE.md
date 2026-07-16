# LLM 优化代码编写指南

## 概述

本指南旨在帮助开发者编写对LLM（大语言模型）友好的代码，提高AI阅读和理解代码的效率，减少无效的token消耗。

## 核心原则

### 1. 函数自包含
```python
# ✅ 好的做法：函数内导入，减少上下文依赖
def process_data():
    import pandas as pd
    import numpy as np
    # 函数逻辑...

# ❌ 不好的做法：顶部导入过多依赖
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
# ... 更多导入

def process_data():
    # 函数逻辑...
```

### 2. 函数长度控制
- **理想长度**: 15-30行
- **最大长度**: 50行
- **超过50行**: 必须拆分

```python
# ✅ 好的做法：拆分成小函数
def process_user_data(user_input):
    # 步骤1: 验证输入
    validated_data = validate_input(user_input)
    
    # 步骤2: 转换数据格式
    transformed_data = transform_data(validated_data)
    
    # 步骤3: 保存到数据库
    save_to_database(transformed_data)
    
    return transformed_data

# ❌ 不好的做法：一个函数包含所有逻辑
def process_user_data(user_input):
    # 100行代码...
```

### 3. 详细的类型提示
```python
# ✅ 好的做法：完整的类型提示
def calculate_metrics(
    data: list[dict[str, Any]], 
    threshold: float = 0.5,
    include_details: bool = False
) -> dict[str, float]:
    """计算数据指标。
    
    Args:
        data: 输入数据列表
        threshold: 阈值参数
        include_details: 是否包含详细信息
        
    Returns:
        包含计算结果的字典
    """
    pass

# ❌ 不好的做法：缺少类型提示
def calculate_metrics(data, threshold, include_details):
    pass
```

### 4. 详细的文档字符串
```python
# ✅ 好的做法：详细的文档字符串
def process_image(
    image_path: str,
    output_format: str = "png",
    quality: int = 95
) -> str:
    """处理图像文件。
    
    该函数读取指定路径的图像文件，进行格式转换和质量优化，
    然后保存到指定位置。
    
    Args:
        image_path: 输入图像文件路径
        output_format: 输出格式，支持 'png', 'jpg', 'webp'
        quality: 输出质量，范围 1-100
        
    Returns:
        处理后的图像文件路径
        
    Raises:
        FileNotFoundError: 输入文件不存在
        ValueError: 不支持的输出格式
        
    Example:
        >>> output_path = process_image("input.jpg", "png", 90)
        >>> print(output_path)
        "input.png"
    """
    pass
```

### 5. 显式错误处理
```python
# ✅ 好的做法：显式捕获和处理错误
def load_config(config_path: str) -> dict:
    """加载配置文件。"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"配置文件不存在: {config_path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"配置文件格式错误: {e}")
        return {}

# ❌ 不好的做法：忽略错误处理
def load_config(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        return json.load(f)
```

## LLM优化策略

### 1. 函数拆分策略

**问题**: 函数过长（>50行）
**解决方案**: 按功能拆分成多个子函数

```python
# 拆分前
def process_data(data):
    # 100行代码...
    pass

# 拆分后
def process_data(data):
    """处理数据的主函数。"""
    validated_data = validate_input(data)
    transformed_data = transform_data(validated_data)
    result = save_to_database(transformed_data)
    return result

def validate_input(data):
    """验证输入数据。"""
    # 20行代码...
    pass

def transform_data(data):
    """转换数据格式。"""
    # 20行代码...
    pass

def save_to_database(data):
    """保存数据到数据库。"""
    # 20行代码...
    pass
```

### 2. 导入优化策略

**问题**: 文件顶部导入过多
**解决方案**: 函数内按需导入

```python
# 拆分前
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import sklearn
import tensorflow as tf
# ... 更多导入

# 拆分后
def analyze_data():
    import pandas as pd
    import numpy as np
    # 分析逻辑...

def visualize_results():
    import matplotlib.pyplot as plt
    import seaborn as sns
    # 可视化逻辑...

def train_model():
    import sklearn
    import tensorflow as tf
    # 训练逻辑...
```

### 3. 类型提示策略

**问题**: 缺少类型提示
**解决方案**: 添加完整的类型注解

```python
# 拆分前
def process(data, config, options):
    pass

# 拆分后
def process(
    data: list[dict[str, Any]],
    config: ProcessConfig,
    options: ProcessOptions | None = None
) -> ProcessResult:
    """处理数据。"""
    pass
```

### 4. 文档字符串策略

**问题**: 缺少文档字符串
**解决方案**: 添加详细的函数文档

```python
# 拆分前
def calculate(a, b):
    return a + b

# 拆分后
def calculate(a: float, b: float) -> float:
    """计算两个数的和。
    
    Args:
        a: 第一个数字
        b: 第二个数字
        
    Returns:
        两个数字的和
        
    Example:
        >>> calculate(1, 2)
        3
    """
    return a + b
```

## 代码审查清单

### ✅ 必须检查项

1. **函数长度**
   - [ ] 函数不超过50行
   - [ ] 复杂函数已拆分成子函数

2. **类型提示**
   - [ ] 所有函数参数有类型提示
   - [ ] 函数返回值有类型提示

3. **文档字符串**
   - [ ] 所有公共函数有文档字符串
   - [ ] 文档字符串包含Args、Returns、Raises

4. **错误处理**
   - [ ] 关键操作有try-except处理
   - [ ] 错误信息清晰明确

5. **导入管理**
   - [ ] 文件顶部导入不超过20个
   - [ ] 不常用导入在函数内部

### ⚠️ 警告项

1. **代码复杂度**
   - [ ] 嵌套深度不超过4层
   - [ ] 条件分支不超过10个

2. **命名规范**
   - [ ] 函数名具有描述性
   - [ ] 变量名清晰易懂

3. **注释质量**
   - [ ] 复杂逻辑有注释说明
   - [ ] 注释与代码保持同步

## 工具使用

### 1. LLM友好度分析工具

```bash
# 分析单个文件
python analyze_llm_friendly.py path/to/file.py

# 分析整个目录
python analyze_llm_friendly.py path/to/directory/

# 分析目录（不递归）
python analyze_llm_friendly.py path/to/directory/ --no-recursive
```

### 2. 代码格式化工具

```bash
# 使用black格式化代码
black path/to/file.py

# 使用ruff检查代码
ruff check path/to/file.py
```

## 最佳实践

### 1. 函数设计原则

- **单一职责**: 每个函数只做一件事
- **高内聚低耦合**: 函数内部紧密相关，函数之间松散耦合
- **可测试性**: 函数易于单元测试

### 2. 代码组织原则

- **模块化**: 相关功能组织在同一模块
- **分层设计**: 清晰的层次结构
- **依赖管理**: 明确的依赖关系

### 3. 文档维护原则

- **及时更新**: 代码修改时同步更新文档
- **示例代码**: 提供使用示例
- **版本控制**: 文档与代码一起版本控制

## 性能考虑

### 1. Token消耗优化

- **减少上下文**: 函数自包含减少上下文依赖
- **精简代码**: 移除不必要的代码和注释
- **优化命名**: 使用简洁但有描述性的命名

### 2. 阅读效率优化

- **结构清晰**: 清晰的代码结构
- **逻辑连贯**: 逻辑流程自然连贯
- **重点突出**: 关键逻辑突出显示

## 总结

LLM优化的代码应该：

1. **易于理解**: 清晰的结构和命名
2. **易于维护**: 模块化和文档化
3. **易于测试**: 函数独立和类型明确
4. **高效阅读**: 减少无效token消耗

通过遵循这些指南，可以显著提高AI阅读和理解代码的效率，减少token消耗，提高开发效率。
