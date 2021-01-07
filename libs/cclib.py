#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
# Copyright 2019 黎慧剑
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
针对CC封装的通用类库
@module cclib
@file cclib.py
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import os
import sys
import time
import copy
import xlwt
import math
import shutil
import traceback
from PIL import Image
from bs4 import BeautifulSoup, PageElement
from HiveNetLib.base_tools.file_tool import FileTool
from HiveNetLib.base_tools.string_tool import StringTool

# 生成TFRecord文件依赖的包
import io
import pandas as pd
import tensorflow as tf
import xml.etree.ElementTree as ET

from object_detection.utils import dataset_util
from collections import namedtuple, OrderedDict


# 标准参数名转换字典
PROP_NAME_TRAN_DICT = {
    '店名': 'shop_name',
    '店铺地址': 'shop_url',
    '价格': 'price',
    '品牌': 'brand',
    '种地类型': 'species_type',
    '款式': 'type',
    '挂件类型': 'pendant_type',
    '鉴定标识': 'identify_type',
    '鉴定类别': 'identify',
    '价格区间': 'price_area',
    '颜色': 'color',
    '颜色1': 'color1',
    '颜色2': 'color2',
    '描述': 'description'
}

# 标注款式转换字典
PROP_TYPE_TRAN_DICT = {
    '手镯': 'bangle',
    '戒指': 'ring',
    '挂件': 'pendant',
    '耳饰': 'earrings',
    '手链': 'chain_bracelet',
    '项链': 'necklace',
    '原石': 'stone',
    '串珠': 'chain_beads',
    '链饰': 'chain',
    '珠子': 'beads',
    '片料': 'sheet_stock'
}

# 不同店铺的参数名转换字典
SHOP_PROP_NAME_TRAN_DICT = {
    '兄弟翡翠挂件店': {
        '认证标识': '鉴定标识',
    }
}

# 不同店铺的产品参数转换字典
SHOP_PROP_TRAN_DICT = {
    '绿翠永恒旗舰店': {
        '款式': {
            '手镯': '手镯',
            '吊坠': '挂件',
            '戒指/指环': '戒指',
            '耳饰': '耳饰',
            '手链': '手链',
            '项链': '项链'
        },
    },
    '兄弟翡翠挂件店': {
        '款式': {
            '手镯': '手镯',
            '金镶玉': '挂件',
            '吊坠': '挂件',
            '戒指/指环': '戒指',
            '戒指': '戒指',
            '戒面': '戒指',
            '耳饰': '耳饰',
            '手链': '手链',
            '项链': '项链',
            '其他款式': '其他',
        }
    }
}

# 不同店铺的描述匹配词典
SHOP_PROP_MATCH_DICT = {
    '绿翠永恒旗舰店': {
        '颜色': {
            '飘': '飘花', '墨绿': '乌鸡', '黑': '黑', '雪': '白', '白': '白', '黄': '黄',
            '红': '红', '蓝': '蓝', '紫': '紫', '绿': '绿',
        },
        '挂件类型': {
            '平安扣': '平安扣', '无事牌': '无事牌', '山水牌': '山水牌', '佛牌': '佛牌', '观音牌': '观音牌',
            '葫芦': '葫芦', '如意': '如意', '蛋面': '蛋面', '貔貅': '貔貅',
            '福豆': '福豆', '福瓜': '福瓜', '福袋': '福袋', '如来': '如来', '佛': '佛公',
            '观音': '观音', '渡母': '渡母', '叶': '叶子'
        }
    },
    '兄弟翡翠挂件店': {
        '颜色': {
            '飘': '飘花', '墨绿': '乌鸡', '黑': '黑', '雪': '白', '白': '白', '黄': '黄',
            '红': '红', '蓝': '蓝', '紫': '紫', '绿': '绿',
        },
        '挂件类型': {
            '平安扣': '平安扣', '无事牌': '无事牌', '山水牌': '山水牌', '佛牌': '佛牌', '观音牌': '观音牌',
            '葫芦': '葫芦', '如意': '如意', '蛋面': '蛋面', '貔貅': '貔貅',
            '福豆': '福豆', '福瓜': '福瓜', '福袋': '福袋', '如来': '如来', '佛': '佛公',
            '观音': '观音', '渡母': '渡母', '叶': '叶子'
        }
    },
}

# 清除特定大小的图片
DEL_SHOP_PIC_SIZE = {
    '绿翠永恒旗舰店': [
        3122387, 288428,
    ],
    '兄弟翡翠挂件店': [
        82167, 188754, 118550, 203311,
    ],
}


class CommonLib(object):
    """
    CC通用库
    """

    #############################
    # 公共函数
    #############################
    @classmethod
    def get_dom_file_list(cls, path: str):
        """
        获取指定目录下需要处理的dom文件清单

        @param {str} path - 要处理的主目录
        """
        _file_list = []
        if not os.path.exists(path):
            return _file_list

        # 遍历获取所有 dom.html 文件
        cls._get_dom_files(path, _file_list)

        return _file_list

    @classmethod
    def analyse_dom_file(cls, file: str, redo=False) -> bool:
        """
        解析dom文件，在相同目录生成info.json字典文件

        @param {str} file - dom.html文件
        @param {bool} redo - 是否要重做

        @returns {bool} - 返回处理结果
        """
        _path = os.path.split(file)[0]
        _save_path = os.path.join(_path, 'info.json')

        # 判断是否已经处理过
        if not redo and os.path.exists(_save_path):
            return True

        try:
            # 获取文件内容
            _html = ''
            with open(file, 'r', encoding='utf-8') as f:
                _html = f.read()

            # 开始解析
            _info = dict()
            _soup = BeautifulSoup(_html, 'html.parser')

            # 店铺信息
            _element = _soup.find('a', attrs={'class': 'slogo-shopname'})
            if _element is not None:
                # 天猫
                _info['店名'] = _element.strong.string
                _info['店铺地址'] = _element['href']
            else:
                # 淘宝
                _element = _soup.find('div', attrs={'class': 'tb-shop-name'})
                _info['店名'] = _element.dl.dd.strong.a['title']
                _info['店铺地址'] = _element.dl.dd.strong.a['href']

            # 价格
            _element = _soup.find('span', attrs={'class': 'tm-price'})
            if _element is not None:
                _info['价格'] = _element.string
            else:
                _element = _soup.find('strong', attrs={'id': 'J_StrPrice'})
                _info['价格'] = _element.em.next_sibling.string

            # 标准参数获取
            _prop_name_tran_dict = {}
            if _info['店名'] in SHOP_PROP_NAME_TRAN_DICT.keys():
                _prop_name_tran_dict = SHOP_PROP_NAME_TRAN_DICT[_info['店名']]

            _element = _soup.find('ul', attrs={'id': 'J_AttrUL'})
            if _element is None:
                _element = _soup.find('ul', attrs={'class': 'attributes-list'})

            for _li in _element.children:
                if _li.name != 'li':
                    continue
                # 解析文本
                _prop_str: str = _li.string
                _index = _prop_str.find(':')
                if _index == -1:
                    continue
                _prop_name = _prop_str[0:_index].strip()
                _prop_value = _prop_str[_index + 1:].strip()

                # 转换标准名
                if _prop_name in _prop_name_tran_dict.keys():
                    _prop_name = _prop_name_tran_dict[_prop_name]

                _info[_prop_name] = _prop_value

            # 各店铺自有参数获取
            if _info['店名'] in SHOP_PROP_SELF_FUN.keys():
                SHOP_PROP_SELF_FUN[_info['店名']](_soup, _info)

            # 转换标准参数值
            for _key in SHOP_PROP_TRAN_DICT[_info['店名']].keys():
                if _key in _info.keys():
                    _value = _info[_key]
                    if _value in SHOP_PROP_TRAN_DICT[_info['店名']][_key].keys():
                        _info[_key] = SHOP_PROP_TRAN_DICT[_info['店名']][_key][_value]
                    else:
                        print('%s not in SHOP_PROP_TRAN_DICT["%s"]["%s"]' % (
                            _value, _info['店名'], _key))

            # # 测试
            # print(_info)
            # return True

            # 保存JSON文件
            _json = str(_info)
            with open(_save_path, 'wb') as f:
                f.write(str.encode(_json, encoding='utf-8'))

            return True
        except:
            print('analyse_dom_file error: %s\r\n%s' % (file, traceback.format_exc()))
            return False

    @classmethod
    def product_info_to_xls(cls, path: str) -> bool:
        """
        将产品信息写入excel文件

        @param {str} path - 要获取产品信息的目录

        @returns {bool} - 处理是否成功
        """
        try:
            # 标题行
            _title = dict()
            _col = 2
            for _key in PROP_NAME_TRAN_DICT.keys():
                _title[_key] = _col
                _col += 1

            # 创建excel文件
            _xls_file = os.path.join(path, 'product_info_list.xls')
            if os.path.exists(_xls_file):
                # 删除文件
                FileTool.remove_file(_xls_file)

            # 创建一个新的Workbook
            _book = xlwt.Workbook()
            _sheet = _book.add_sheet('product_info')  # 在工作簿中新建一个表格

            # 写入标题
            _sheet.write(0, 0, '网站产品ID')
            _sheet.write(0, 1, '产品目录')
            for _word in _title.keys():
                print()
                _sheet.write(0, _title[_word], _word)

            _current_row = [1]  # 当前行

            # 逐个产品进行写入
            cls._write_product_info_to_xls(path, _sheet, _title, _current_row)

            # 保存excel
            _book.save(_xls_file)
            return True
        except:
            print('product_info_to_xls error:\r\n%s' % (traceback.format_exc(), ))
            return False

    @classmethod
    def clean_file_path(cls, path: str):
        """
        清理文件目录
        1、批量删除带括号的图片文件(重复下载)
        2、删除宣传图片
        2、将文件名修改为"产品编号_main/detail_序号"的格式
        3、将文件夹按款式进行分类

        @param {str} path - 要清理的文件夹

        @return {iter_list} - 通过yield返回的处理进度信息清单
            [总文件数int, 当前已处理文件数int, 是否成功]
        """
        try:
            _path = path
            if not (_path.endswith('/') or _path.endswith('\\')):
                _path = _path + '/'

            # 创建分类目录
            _class_path = os.path.join(
                FileTool.get_parent_dir(_path),
                FileTool.get_dir_name(_path) + '_class'
            )
            if not os.path.exists(_class_path):
                FileTool.create_dir(_class_path, exist_ok=True)

            # 获取目录清单
            _dir_list = cls._get_child_dir_list(path, with_root=True)
            _total = len(_dir_list)
            _deal_num = 0

            # 先返回进度情况
            if _total == 0:
                yield [_deal_num, _total, True]
                return

            # 遍历目录执行处理
            for _dir in _dir_list:
                yield [_deal_num, _total, True]
                cls._clean_file_path(_dir, _class_path)
                _deal_num += 1

            yield [_deal_num, _total, True]
        except:
            print('clean_file_path error: %s\r\n%s' % (path, traceback.format_exc()))
            yield [-1, -1, False]

    #############################
    # 内部函数
    #############################
    @classmethod
    def _get_dom_files(cls, path: str, files: list):
        """
        获取指定目录下的所有dom.html文件

        @param {str} path - 路径
        @param {list} files - 找到的文件清单
        """
        # 先找当前目录下的文件
        _temp_list = FileTool.get_filelist(path, regex_str=r'^dom\.html$', is_fullname=True)
        files.extend(_temp_list)

        # 遍历所有子目录获取文件
        _dirs = FileTool.get_dirlist(path)
        for _dir in _dirs:
            cls._get_dom_files(_dir, files)

    @classmethod
    def _get_match_info(cls, _str: str, match_list: dict) -> list:
        """
        从字符串中获取match_list对应的字符

        @param {str} _str - 要匹配的字符串
        @param {dict} match_list - 比较清单

        @returns {list} - 按顺序匹配到的字符
        """
        _list = []
        for _matc_str in match_list.keys():
            if _str.find(_matc_str) != -1:
                _list.append(match_list[_matc_str])

        return _list

    @classmethod
    def _write_product_info_to_xls(cls, path: str, sheet, title: dict, current_row: list):
        """
        按目录逐个将产品信息写入excel文件>

        @param {str} path - 要处理的目录
        @param {object} sheet - excel的sheet对象
        @param {dict} title - 标题清单
        @param {list} current_row - 当前行
        """
        # 先处理自己
        _info_file = os.path.join(path, 'info.json')
        if os.path.exists(_info_file):
            # 有信息文件才处理
            _info = dict()
            with open(_info_file, 'rb') as f:
                _eval = str(f.read(), encoding='utf-8')
                _info = eval(_eval)

            # 产品编号和产品目录
            _product_num = FileTool.get_dir_name(path)
            sheet.write(current_row[0], 0, _product_num)
            sheet.write(current_row[0], 1, path)

            # 逐个信息项写入
            for _key in _info.keys():
                if _key in title.keys():
                    sheet.write(current_row[0], title[_key], _info[_key])
                else:
                    # 要新增列标题
                    _col = len(title) + 2
                    title[_key] = _col
                    sheet.write(0, _col, _key)
                    # 写入信息值
                    sheet.write(current_row[0], _col, _info[_key])

            # 换到下一行
            current_row[0] += 1

        # 处理子目录
        _dirs = FileTool.get_dirlist(path)
        for _dir in _dirs:
            cls._write_product_info_to_xls(_dir, sheet, title, current_row)

    @classmethod
    def _get_child_dir_list(cls, path: str, with_root: bool = True) -> list:
        """
        获取目录及子目录清单
        (保证顺序为先子目录，再父目录)

        @param {str} path - 开始目录
        @param {bool} with_root=True - 是否包含当前目录

        @returns {list} - 文件夹清单
        """
        _list = []

        for _dir in FileTool.get_dirlist(path):
            _temp_list = cls._get_child_dir_list(_dir, with_root=True)
            _list.extend(_temp_list)

        if with_root:
            _list.append(path)

        return _list

    @classmethod
    def _clean_file_path(cls, path: str, class_path: str):
        """
        清理当前目录文件

        @param {str} path - 要处理的目录地址
        @param {str} class_path - 类目录
        """
        # 处理自身目录，先获取商品信息
        _info = dict()
        _info_file = os.path.join(path, 'info.json')
        if os.path.exists(_info_file):
            with open(_info_file, 'rb') as f:
                _eval = str(f.read(), encoding='utf-8')
                _info = eval(_eval)

            # 判断是否不处理
            _shop_name = _info['店名']
            # if _info['款式'] == '挂件' and _info['挂件类型'] == '':
            #     return

            # 遍历文件进行处理
            _product_num = FileTool.get_dir_name(path)
            _files = FileTool.get_filelist(path)
            _order = 1
            for _file in _files:
                _file_ext = FileTool.get_file_ext(_file).lower()
                if _file_ext not in ['jpg', 'jpeg', 'png', 'bmp']:
                    # 不是合适的文件类型
                    continue

                # 判断是否有括号
                if _file.find('(') >= 0:
                    FileTool.remove_file(_file)
                    continue

                # 判断是否匹配上要删除的图片大小
                if _shop_name in DEL_SHOP_PIC_SIZE.keys() and os.path.getsize(_file) in DEL_SHOP_PIC_SIZE[_shop_name]:
                    FileTool.remove_file(_file)
                    continue

                # 修改文件名
                if not FileTool.get_file_name(_file).startswith(_product_num):
                    os.rename(
                        _file, os.path.join(
                            path, '%s_%s_%d.%s' % (
                                _product_num,
                                'main' if _file.find('主图') >= 0 or _file.find(
                                    'main') >= 0 else 'detail',
                                _order, _file_ext
                            )
                        )
                    )

                # 下一个文件
                _order += 1

            # 移动文件夹到指定的分类目录
            _class_path = _info['款式']
            if _class_path in PROP_TYPE_TRAN_DICT.keys():
                _class_path = PROP_TYPE_TRAN_DICT[_info['款式']]
            shutil.move(
                path,
                os.path.join(class_path, _class_path, _product_num)
            )

        # 处理完成，返回
        return

    @classmethod
    def _get_prop_self_lcyh(cls, soup: BeautifulSoup, info: dict):
        """
        获取属性的自有方法
        (绿翠永恒旗舰店)

        @param {BeautifulSoup} soup - 页面解析对象
        @param {dict} info - 返回的字典
        """
        # 获取描述页面
        _element: PageElement = soup.find('div', attrs={'id': 'description'})
        _spans = _element.find_all('span')
        _desc_list = []
        for _span in _spans:
            if _span.string is None:
                continue
            _desc = _span.string.strip()
            _desc_list.append(_desc)
            if _desc.startswith('【描述】'):
                for _key in SHOP_PROP_MATCH_DICT['绿翠永恒旗舰店'].keys():
                    _match = cls._get_match_info(
                        _desc, SHOP_PROP_MATCH_DICT['绿翠永恒旗舰店'][_key]
                    )
                    if len(_match) > 1 and _key == '颜色' and _match[0] == '飘花':
                        # 飘花，有两种颜色
                        info[_key] = _match[0]
                        info['颜色1'] = _match[1]
                        if len(_match) > 2:
                            info['颜色2'] = _match[2]
                    elif _key == '挂件类型' and len(_match) > 0:
                        # 把挂件类型直接放到款式里面
                        info['款式'] = _match[0]
                    else:
                        if len(_match) > 0:
                            info[_key] = _match[0]
                        else:
                            info[_key] = ''

            elif _desc.startswith('【产地】'):
                info['产地'] = _desc[4:].strip()

        # 添加描述
        info['描述'] = '\n'.join(_desc_list)

    @classmethod
    def _get_prop_self_xdfcgjd(cls, soup: BeautifulSoup, info: dict):
        """
        获取属性的自有方法
        (兄弟翡翠挂件店)

        @param {BeautifulSoup} soup - 页面解析对象
        @param {dict} info - 返回的字典
        """
        # 获取描述页面
        _element: PageElement = soup.find('div', attrs={'id': 'J_DivItemDesc'})

        # 获取详细描述
        _desc_list = []
        for _p in _element.children:
            if _p.name != 'p':
                continue
            if _p.span is not None and _p.span.span is not None:
                _str = ''
                for _font in _p.span.span.children:
                    if _font.string is not None:
                        _str += _font.string
                _desc_list.append(_str)

        # 添加描述
        info['描述'] = '\n'.join(_desc_list)

        # 根据描述获取信息
        for _key in SHOP_PROP_MATCH_DICT['兄弟翡翠挂件店'].keys():
            _match = cls._get_match_info(
                info['描述'], SHOP_PROP_MATCH_DICT['兄弟翡翠挂件店'][_key]
            )
            if len(_match) > 1 and _key == '颜色' and _match[0] == '飘花':
                # 飘花，有两种颜色
                info[_key] = _match[0]
                info['颜色1'] = _match[1]
                if len(_match) > 2:
                    info['颜色2'] = _match[2]
            elif _key == '挂件类型' and len(_match) > 0:
                # 把挂件类型直接放到款式里面
                info['款式'] = _match[0]
            else:
                if len(_match) > 0:
                    info[_key] = _match[0]
                else:
                    info[_key] = ''


# 不同店铺的个性获取私有函数
SHOP_PROP_SELF_FUN = {
    '绿翠永恒旗舰店': CommonLib._get_prop_self_lcyh,
    '兄弟翡翠挂件店': CommonLib._get_prop_self_xdfcgjd,
}


if __name__ == '__main__':
    # 当程序自己独立运行时执行的操作
    pass
