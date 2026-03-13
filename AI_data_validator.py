#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# 模块：基础设施 - 数据验证
# 文件：AI_data_validator.py  [AI创建]
# 用途：验证K线数据的质量和完整性：
#       - 检查必需字段（t/o/c/h/l/v）、价格正数、高低价关系
#       - 检查时间连续性（缺失时间点）
#       - 检测价格异常波动（>50%）和成交量异常（>10倍均值）
#       提供 validate_kline_data(records) 便捷函数。
# 被依赖：AI_collect_dual_kline, AI_collect_latest
# =============================================================================
"""
数据验证模块 - 验证K线数据的质量和完整性
"""

from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone


class DataValidator:
    """K线数据验证器"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def validate_record(self, record: Dict) -> bool:
        """
        验证单条记录的合理性
        
        Args:
            record: K线记录字典
        
        Returns:
            是否通过验证
        """
        try:
            # 检查必需字段
            required_fields = ["t", "o", "c", "h", "l", "v"]
            for field in required_fields:
                if field not in record:
                    self.errors.append(f"缺少字段: {field}")
                    return False
            
            # 检查价格是否为正数
            if record["o"] <= 0 or record["c"] <= 0:
                self.errors.append(f"价格必须为正数: o={record['o']}, c={record['c']}")
                return False
            
            # 检查高低价关系
            if record["h"] < record["l"]:
                self.errors.append(f"最高价不能低于最低价: h={record['h']}, l={record['l']}")
                return False
            
            # 检查开盘价是否在高低价范围内
            if not (record["l"] <= record["o"] <= record["h"]):
                self.warnings.append(f"开盘价超出高低价范围: o={record['o']}, h={record['h']}, l={record['l']}")
            
            # 检查收盘价是否在高低价范围内
            if not (record["l"] <= record["c"] <= record["h"]):
                self.warnings.append(f"收盘价超出高低价范围: c={record['c']}, h={record['h']}, l={record['l']}")
            
            # 检查成交量
            if record["v"] < 0:
                self.errors.append(f"成交量不能为负数: v={record['v']}")
                return False
            
            return True
            
        except Exception as e:
            self.errors.append(f"验证异常: {e}")
            return False
    
    def check_continuity(self, records: List[Dict], interval_ms: int = 3600000) -> List[Tuple[int, int]]:
        """
        检查时间连续性
        
        Args:
            records: K线记录列表（已排序）
            interval_ms: 预期时间间隔（毫秒），默认1小时
        
        Returns:
            缺失的时间段列表 [(start_ts, end_ts), ...]
        """
        gaps = []
        
        for i in range(1, len(records)):
            prev_ts = int(records[i-1]["t"])
            curr_ts = int(records[i]["t"])
            expected_ts = prev_ts + interval_ms
            
            if curr_ts != expected_ts:
                gap_count = (curr_ts - expected_ts) // interval_ms
                if gap_count > 0:
                    gaps.append((prev_ts, curr_ts))
                    self.warnings.append(
                        f"时间间隔异常: {self._format_ts(prev_ts)} → {self._format_ts(curr_ts)} "
                        f"(缺失 {gap_count} 个时间点)"
                    )
        
        return gaps
    
    def check_price_anomaly(self, records: List[Dict], threshold: float = 0.5) -> List[Dict]:
        """
        检查价格异常波动
        
        Args:
            records: K线记录列表
            threshold: 异常阈值（50%变化）
        
        Returns:
            异常记录列表
        """
        anomalies = []
        
        for i in range(1, len(records)):
            prev_close = float(records[i-1]["c"])
            curr_open = float(records[i]["o"])
            
            if prev_close > 0:
                change_ratio = abs(curr_open - prev_close) / prev_close
                
                if change_ratio > threshold:
                    anomalies.append(records[i])
                    self.warnings.append(
                        f"价格异常波动: {self._format_ts(records[i]['t'])} "
                        f"变化 {change_ratio*100:.1f}% (前收={prev_close}, 当开={curr_open})"
                    )
        
        return anomalies
    
    def check_volume_anomaly(self, records: List[Dict], threshold: float = 10.0) -> List[Dict]:
        """
        检查成交量异常
        
        Args:
            records: K线记录列表
            threshold: 异常阈值（10倍）
        
        Returns:
            异常记录列表
        """
        anomalies = []
        
        # 计算平均成交量
        volumes = [float(r["v"]) for r in records if r["v"] > 0]
        if not volumes:
            return anomalies
        
        avg_volume = sum(volumes) / len(volumes)
        
        for record in records:
            volume = float(record["v"])
            
            if volume > avg_volume * threshold:
                anomalies.append(record)
                self.warnings.append(
                    f"成交量异常: {self._format_ts(record['t'])} "
                    f"成交量={volume:.1f} (平均={avg_volume:.1f}, {volume/avg_volume:.1f}倍)"
                )
        
        return anomalies
    
    def validate_dataset(
        self,
        records: List[Dict],
        check_continuity: bool = True,
        check_price: bool = True,
        check_volume: bool = True
    ) -> Dict:
        """
        完整验证数据集
        
        Args:
            records: K线记录列表
            check_continuity: 是否检查连续性
            check_price: 是否检查价格异常
            check_volume: 是否检查成交量异常
        
        Returns:
            验证结果字典
        """
        self.errors = []
        self.warnings = []
        
        if not records:
            self.errors.append("数据集为空")
            return self._get_result()
        
        # 验证每条记录
        valid_count = 0
        for i, record in enumerate(records):
            if self.validate_record(record):
                valid_count += 1
        
        # 检查连续性
        gaps = []
        if check_continuity and len(records) > 1:
            gaps = self.check_continuity(records)
        
        # 检查价格异常
        price_anomalies = []
        if check_price and len(records) > 1:
            price_anomalies = self.check_price_anomaly(records)
        
        # 检查成交量异常
        volume_anomalies = []
        if check_volume and len(records) > 1:
            volume_anomalies = self.check_volume_anomaly(records)
        
        return {
            "total_records": len(records),
            "valid_records": valid_count,
            "invalid_records": len(records) - valid_count,
            "time_gaps": len(gaps),
            "price_anomalies": len(price_anomalies),
            "volume_anomalies": len(volume_anomalies),
            "errors": self.errors,
            "warnings": self.warnings,
            "passed": len(self.errors) == 0
        }
    
    def _get_result(self) -> Dict:
        """获取验证结果"""
        return {
            "total_records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "time_gaps": 0,
            "price_anomalies": 0,
            "volume_anomalies": 0,
            "errors": self.errors,
            "warnings": self.warnings,
            "passed": len(self.errors) == 0
        }
    
    def _format_ts(self, ts_ms: int) -> str:
        """格式化时间戳"""
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    
    def print_report(self, result: Dict):
        """打印验证报告"""
        print("=" * 60)
        print("数据验证报告")
        print("=" * 60)
        print(f"总记录数: {result['total_records']}")
        print(f"有效记录: {result['valid_records']}")
        print(f"无效记录: {result['invalid_records']}")
        print(f"时间间隔: {result['time_gaps']} 个")
        print(f"价格异常: {result['price_anomalies']} 个")
        print(f"成交量异常: {result['volume_anomalies']} 个")
        print()
        
        if result['errors']:
            print(f"❌ 错误 ({len(result['errors'])} 个):")
            for error in result['errors'][:10]:
                print(f"   • {error}")
            if len(result['errors']) > 10:
                print(f"   • ... 还有 {len(result['errors']) - 10} 个错误")
            print()
        
        if result['warnings']:
            print(f"⚠️  警告 ({len(result['warnings'])} 个):")
            for warning in result['warnings'][:10]:
                print(f"   • {warning}")
            if len(result['warnings']) > 10:
                print(f"   • ... 还有 {len(result['warnings']) - 10} 个警告")
            print()
        
        if result['passed']:
            print("✅ 数据验证通过")
        else:
            print("❌ 数据验证失败")
        
        print("=" * 60)


def validate_kline_data(records: List[Dict], verbose: bool = True) -> Dict:
    """
    便捷函数：验证K线数据
    
    Args:
        records: K线记录列表
        verbose: 是否打印详细报告
    
    Returns:
        验证结果字典
    """
    validator = DataValidator()
    result = validator.validate_dataset(records)
    
    if verbose:
        validator.print_report(result)
    
    return result


if __name__ == "__main__":
    # 测试
    print("数据验证模块测试")
    print()
    
    # 测试数据
    test_records = [
        {"t": 1000000, "o": 100, "c": 105, "h": 110, "l": 95, "v": 10},
        {"t": 4600000, "o": 105, "c": 102, "h": 108, "l": 100, "v": 15},  # 正常
        {"t": 8200000, "o": 102, "c": 101, "h": 105, "l": 99, "v": 12},   # 正常
        {"t": 11800000, "o": 200, "c": 205, "h": 210, "l": 195, "v": 100}, # 价格异常
    ]
    
    result = validate_kline_data(test_records)
