"""
会话 Pipeline 模块
将对话流程拆分为可配置的步骤，支持跳过、重新排序和自定义插件

设计思路:
- 每个步骤是一个独立的函数/方法
- 步骤通过名称标识，可以配置启用/禁用
- 步骤按配置的顺序执行
- 支持自定义步骤插入
"""

from typing import List, Dict, Callable, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class PipelineStep:
    """Pipeline 步骤定义"""
    name: str  # 步骤名称（唯一标识）
    func: Callable  # 执行函数
    enabled: bool = True  # 是否启用
    description: str = ""  # 步骤描述
    position: int = 0  # 执行顺序（越小越先执行）


class SessionPipeline:
    """
    会话 Pipeline 管理器
    
    管理对话流程的步骤，支持：
    - 启用/禁用步骤
    - 重新排序步骤
    - 插入自定义步骤
    - 跳过步骤
    """
    
    def __init__(self):
        self._steps: Dict[str, PipelineStep] = {}
        self._step_order: List[str] = []  # 步骤执行顺序
        
    def register_step(
        self,
        name: str,
        func: Callable,
        enabled: bool = True,
        description: str = "",
        position: int = 0,
        before: Optional[str] = None,
        after: Optional[str] = None,
    ):
        """
        注册一个 Pipeline 步骤。
        
        Args:
            name: 步骤名称（唯一标识）
            func: 执行函数，签名为 (self, **kwargs) -> dict
            enabled: 是否启用
            description: 步骤描述
            position: 执行顺序（越小越先执行）
            before: 在哪个步骤之前执行（可选）
            after: 在哪个步骤之后执行（可选）
        """
        if name in self._steps:
            raise ValueError(f"步骤 '{name}' 已存在")
        
        step = PipelineStep(
            name=name,
            func=func,
            enabled=enabled,
            description=description,
            position=position,
        )
        
        self._steps[name] = step
        
        # 插入到正确的位置
        if before is not None:
            if before in self._step_order:
                idx = self._step_order.index(before)
                self._step_order.insert(idx, name)
            else:
                self._step_order.append(name)
        elif after is not None:
            if after in self._step_order:
                idx = self._step_order.index(after)
                self._step_order.insert(idx + 1, name)
            else:
                self._step_order.append(name)
        else:
            self._step_order.append(name)
        
        # 按 position 排序
        self._step_order.sort(key=lambda n: self._steps[n].position)
        
    def enable_step(self, name: str):
        """启用指定步骤"""
        if name in self._steps:
            self._steps[name].enabled = True
    
    def disable_step(self, name: str):
        """禁用指定步骤"""
        if name in self._steps:
            self._steps[name].enabled = False
    
    def toggle_step(self, name: str):
        """切换步骤的启用/禁用状态"""
        if name in self._steps:
            self._steps[name].enabled = not self._steps[name].enabled
    
    def set_step_position(self, name: str, position: int):
        """设置步骤的执行顺序"""
        if name in self._steps:
            self._steps[name].position = position
            self._step_order.sort(key=lambda n: self._steps[n].position)
    
    def remove_step(self, name: str):
        """移除步骤"""
        if name in self._steps:
            del self._steps[name]
            self._step_order.remove(name)
    
    def get_enabled_steps(self) -> List[Tuple[str, PipelineStep]]:
        """获取所有启用的步骤，按执行顺序排列"""
        return [
            (name, self._steps[name])
            for name in self._step_order
            if self._steps[name].enabled
        ]
    
    def execute(
        self,
        context: Dict[str, Any],
        stop_at: Optional[str] = None,
        skip_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        执行 Pipeline。
        
        Args:
            context: 上下文数据字典，传递给每个步骤
            stop_at: 在此步骤后停止（包含该步骤）
            skip_steps: 要跳过的步骤列表（临时禁用）
            
        Returns:
            更新后的上下文数据字典
        """
        skip_steps = skip_steps or []
        
        for name, step in self.get_enabled_steps():
            # 检查是否要跳过
            if name in skip_steps:
                continue
            
            # 执行步骤
            try:
                result = step.func(context)
                # 合并结果到上下文
                if isinstance(result, dict):
                    context.update(result)
            except Exception as e:
                context.setdefault("_errors", []).append({
                    "step": name,
                    "error": str(e),
                })
            
            # 检查是否要停止
            if stop_at and name == stop_at:
                break
        
        return context
    
    def list_steps(self) -> List[Dict[str, Any]]:
        """列出所有步骤及其状态"""
        return [
            {
                "name": name,
                "enabled": step.enabled,
                "position": step.position,
                "description": step.description,
            }
            for name, step in self.get_enabled_steps()
        ] + [
            {
                "name": name,
                "enabled": step.enabled,
                "position": step.position,
                "description": step.description,
                "disabled": True,
            }
            for name, step in self._steps.items()
            if not step.enabled
        ]
