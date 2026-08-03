"""SpEL-like 表达式解析模块

提供通用的 SpEL 风格表达式解析功能，支持从函数参数中提取值。
可用于锁键生成、日志格式化、缓存键构建等场景。
"""

from __future__ import annotations

import re
from typing import Any


class ExpressionParser:
    """SpEL-like 表达式解析器

    支持解析类似 Spring SpEL 的表达式，从函数参数中提取值。

    表达式语法:
        - #name: 引用名为 name 的参数
        - #0, #1: 引用位置参数（第1个、第2个）
        - #obj.attr: 访问对象的属性
        - #obj.nested.attr: 访问嵌套属性
        - 'string': 字符串字面量
        - 123: 数字字面量

    Examples:
        >>> def example(user, feed_id):
        ...     pass
        >>> # 解析 #user.id -> 获取 user 参数的 id 属性
        >>> # 解析 #feed_id -> 获取 feed_id 参数的值
        >>> # 解析 'custom_key' -> 返回字符串 "custom_key"
    """

    EXPR_PATTERN = re.compile(
        r"^\s*"
        r"(?:(?P<ref>#(?P<ref_name>[a-zA-Z_][a-zA-Z0-9_]*|\d+))"
        r"(?P<chain>(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)"
        r"|(?P<string>'[^']*')"
        r"|(?P<number>-?\d+)"
        r")\s*$"
    )
    COMPARISON_PATTERN = re.compile(
        r"^\s*(?P<left>.+?)\s*(?P<op>>=|<=|==|!=|>|<)\s*(?P<right>.+?)\s*$"
    )

    @classmethod
    def parse(
        cls,
        expr: str,
        args: tuple,
        kwargs: dict,
        param_names: list[str] | None = None,
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
            ValueError: 表达式格式错误或参数不存在
            AttributeError: 属性不存在
            IndexError: 参数索引越界
        """
        if not expr:
            raise ValueError("Expression cannot be empty")

        comparison = cls.COMPARISON_PATTERN.match(expr)
        if comparison:
            left = cls.parse(comparison.group("left"), args, kwargs, param_names)
            right = cls.parse(comparison.group("right"), args, kwargs, param_names)
            match comparison.group("op"):
                case ">":
                    return left > right
                case "<":
                    return left < right
                case ">=":
                    return left >= right
                case "<=":
                    return left <= right
                case "==":
                    return left == right
                case "!=":
                    return left != right

        match = cls.EXPR_PATTERN.match(expr)
        if not match:
            raise ValueError(f"Invalid expression: {expr}")

        if match.group("string") is not None:
            return match.group("string")[1:-1]

        if match.group("number") is not None:
            return int(match.group("number"))

        ref_name = match.group("ref_name")
        chain = match.group("chain") or ""
        chain_attrs = [attr for attr in chain.split(".") if attr]

        if ref_name.isdigit():
            idx = int(ref_name)
            if idx >= len(args):
                raise IndexError(
                    f"Parameter index {idx} out of range (got {len(args)} args)"
                )
            value = args[idx]
        else:
            value = cls._find_param_by_name(ref_name, args, kwargs, param_names)

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
        cls,
        name: str,
        args: tuple,
        kwargs: dict,
        param_names: list[str] | None = None,
    ) -> Any:
        """尝试从 args/kwargs 中查找参数

        查找顺序:
        1. kwargs 中的同名参数
        2. param_names 中对应位置的参数
        3. 第一个参数对象的属性（如果存在）
        """
        if name in kwargs:
            return kwargs[name]

        if param_names and name in param_names:
            idx = param_names.index(name)
            if idx < len(args):
                return args[idx]

        if len(args) > 0 and hasattr(args[0], name):
            try:
                return getattr(args[0], name)
            except AttributeError:
                pass

        raise ValueError(
            f"Cannot resolve parameter '{name}' from {len(args)} positional args "
            f"and kwargs keys {list(kwargs.keys())}"
        )


class ExpressionEvaluator:
    """表达式求值器

    提供更高层次的表达式求值接口，支持预编译和缓存。
    """

    def __init__(self):
        self._cache: dict[str, Any] = {}

    def evaluate(
        self,
        expr: str,
        *args,
        **kwargs,
    ) -> Any:
        """求值表达式

        Args:
            expr: SpEL 表达式
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            表达式求值结果
        """
        return ExpressionParser.parse(expr, args, kwargs)

    def compile(self, expr: str) -> CompiledExpression:
        """预编译表达式以提高重复求值性能

        Args:
            expr: SpEL 表达式

        Returns:
            编译后的表达式对象
        """
        if expr not in self._cache:
            self._cache[expr] = CompiledExpression(expr)
        return self._cache[expr]


class CompiledExpression:
    """预编译的表达式

    可以多次求值而无需重新解析表达式字符串。
    """

    def __init__(self, expr: str):
        self._expr = expr
        self._match = ExpressionParser.EXPR_PATTERN.match(
            expr
        ) or ExpressionParser.COMPARISON_PATTERN.match(expr)
        if not self._match:
            raise ValueError(f"Invalid expression: {expr}")

    def evaluate(
        self,
        args: tuple = (),
        kwargs: dict | None = None,
        param_names: list[str] | None = None,
    ) -> Any:
        """使用给定的上下文求值表达式

        Args:
            args: 位置参数元组
            kwargs: 关键字参数字典
            param_names: 参数名列表

        Returns:
            表达式求值结果
        """
        if kwargs is None:
            kwargs = {}
        return ExpressionParser.parse(self._expr, args, kwargs, param_names)

    def __call__(
        self,
        *args,
        **kwargs,
    ) -> Any:
        """使编译后的表达式可直接调用"""
        return self.evaluate(args, kwargs)


__all__ = [
    "CompiledExpression",
    "ExpressionEvaluator",
    "ExpressionParser",
]
