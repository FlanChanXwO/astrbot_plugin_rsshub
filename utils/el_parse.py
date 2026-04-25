"""SpEL-like Expression Parser

简化版 Spring SpEL 表达式解析器，支持从函数参数中提取值。

支持的语法:
    - #paramName       : 获取参数值（支持 kwargs 和位置参数）
    - #param.attr      : 获取参数的属性
    - #param.attr.sub  : 链式属性访问
    - #0, #1, #2      : 按索引获取位置参数
    - 'string'         : 字符串字面量（作为固定锁名称）
    - 123              : 数字字面量

示例:
    >>> parser = ExpressionParser()
    >>> parser.parse("#feed.id", args=(feed_obj,), kwargs={}, param_names=['feed'])
    42
    >>> parser.parse("#0.id", args=(feed_obj,), kwargs={})
    42
    >>> parser.parse("'fixed_lock_name'", args=(), kwargs={})
    'fixed_lock_name'
"""

from __future__ import annotations

import re
from typing import Any


class ExpressionParser:
    """SpEL-like 表达式解析器"""

    # 匹配表达式: #param.attr 或 #0.attr 或 'string' 或 123
    EXPR_PATTERN = re.compile(
        r"^\s*"
        r"(?:(?P<ref>#(?P<ref_name>[a-zA-Z_][a-zA-Z0-9_]*|\d+))"  # #param 或 #0
        r"(?P<chain>(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)"  # .attr.sub
        r"|(?P<string>'[^']*')"  # 'string literal'
        r"|(?P<number>-?\d+)"  # 123
        r")\s*$"
    )

    @classmethod
    def parse(
        cls, expr: str, args: tuple, kwargs: dict, param_names: list[str] | None = None
    ) -> Any:
        """解析表达式并返回结果

        Args:
            expr: SpEL 表达式
            args: 位置参数元组
            kwargs: 关键字参数字典
            param_names: 参数名列表（用于将位置参数映射到名称）

        Returns:
            解析后的值

        Raises:
            ValueError: 表达式格式错误
            AttributeError: 属性不存在
            IndexError: 参数索引越界
        """
        if not expr:
            raise ValueError("Expression cannot be empty")

        match = cls.EXPR_PATTERN.match(expr)
        if not match:
            raise ValueError(f"Invalid expression: {expr}")

        # 处理字面量
        if match.group("string") is not None:
            # 去除引号
            return match.group("string")[1:-1]

        if match.group("number") is not None:
            num_str = match.group("number")
            return int(num_str)

        # 处理引用
        ref_name = match.group("ref_name")
        chain = match.group("chain") or ""
        chain_attrs = chain.split(".") if chain else []
        chain_attrs = [attr for attr in chain_attrs if attr]  # 过滤空字符串

        # 获取基础值
        if ref_name.isdigit():
            # 按索引获取 (#0, #1, ...)
            idx = int(ref_name)
            if idx >= len(args):
                raise IndexError(
                    f"Parameter index {idx} out of range (got {len(args)} args)"
                )
            value = args[idx]
        else:
            # 按名称获取 (#paramName)
            value = cls._find_param_by_name(ref_name, args, kwargs, param_names)

        # 链式属性访问
        for attr in chain_attrs:
            if value is None:
                raise AttributeError(f"Cannot access attribute '{attr}' on None value")
            if attr.startswith("_"):
                raise AttributeError(
                    f"Cannot access private attribute '{attr}' in expression"
                )
            value = getattr(value, attr)

        return value

    @classmethod
    def _find_param_by_name(
        cls, name: str, args: tuple, kwargs: dict, param_names: list[str] | None = None
    ) -> Any:
        """尝试从 args/kwargs 中查找参数

        策略:
        1. 首先在 kwargs 中查找
        2. 如果提供了 param_names，按名称找到对应的位置参数
        3. 如果找不到，尝试查找绑定到 self 的方法参数
        """
        # 1. 首先在 kwargs 中查找
        if name in kwargs:
            return kwargs[name]

        # 2. 通过 param_names 映射位置参数
        if param_names and name in param_names:
            idx = param_names.index(name)
            if idx < len(args):
                return args[idx]

        # 3. 检查是否是方法调用的第一个参数 (self/cls)
        if len(args) > 0 and hasattr(args[0], name):
            # 尝试从 self 对象获取属性
            try:
                return getattr(args[0], name)
            except AttributeError:
                pass

        raise ValueError(
            f"Cannot resolve parameter '{name}' from {len(args)} positional args "
            f"and kwargs keys {list(kwargs.keys())}"
        )


def parse_expression(expr: str, *args, **kwargs) -> Any:
    """便捷函数：解析表达式

    Args:
        expr: SpEL 表达式
        *args: 位置参数
        **kwargs: 关键字参数

    Returns:
        解析后的值

    Examples:
        >>> parse_expression("#feed.id", feed_obj)
        42
        >>> parse_expression("#0.id", feed_obj)
        42
        >>> parse_expression("'my_lock'")
        'my_lock'
        >>> parse_expression("#user_id", user_id="123")
        '123'
    """
    return ExpressionParser.parse(expr, args, kwargs)
