#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
# Copyright 2019 黎慧剑
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
扩展功能库
@module extend
@file extend.py
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import os
import sys
import time
import numpy as np
import copy
import xlwt
import math
import shutil
import traceback
from io import BytesIO
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


class ExtendLib(object):
    """
    扩展功能类
    """

    @classmethod
    def get_info_dict(cls, image_file: str, key_dict: dict) -> dict:
        """
        通过图片文件路径获取信息字典

        @param {str} image_file - 图片文件
        @param {dict} key_dict - 需要展示信息的模板字典

        @returns {dict}
        """
        _info_dict = dict()
        _path = os.path.split(image_file)[0]
        _file_no_ext = FileTool.get_file_name_no_ext(image_file)
        _info_file = os.path.join(_path, _file_no_ext + ".info")
        if not os.path.exists(_info_file):
            _info_file = os.path.join(_path, 'info.json')

        if os.path.exists(_info_file):
            with open(_info_file, 'rb') as f:
                _eval = str(f.read(), encoding='utf-8')
                _info = eval(_eval)
                _info_dict = copy.deepcopy(key_dict)
                for _key in _info_dict:
                    if _key in _info.keys():
                        _info_dict[_key] = _info[_key]

        return _info_dict

    @classmethod
    def change_info_file(cls, image_file: str, prop_name: str, prop_value: str) -> bool:
        """
        修改指定图片的info文件

        @param {str} image_file - 传入图片文件
        @param {str} prop_name - 属性名
        @param {str} prop_value - 属性值

        @returns {bool} - 处理结果
        """
        _path = os.path.split(image_file)[0]
        _file_no_ext = FileTool.get_file_name_no_ext(image_file)
        _info_file = os.path.join(_path, _file_no_ext + ".info")
        if not os.path.exists(_info_file):
            _info_file = os.path.join(_path, 'info.json')

        if os.path.exists(_info_file):
            # 有信息文件才处理
            _info = dict()
            with open(_info_file, 'rb') as f:
                _eval = str(f.read(), encoding='utf-8')
                _info = eval(_eval)
            _info[prop_name] = prop_value
            # 保存JSON文件
            _json = str(_info)
            with open(_info_file, 'wb') as f:
                f.write(str.encode(_json, encoding='utf-8'))
            return True
        else:
            return False


class TFRecordCreater(object):
    """
    生成TFRecord文件格式的方法
    """
    @classmethod
    def create_pbtxt(cls, save_path: str, mapping: dict) -> bool:
        """
        创建labelmap.pbtxt文件

        @param {str} save_path - 文件保存路径
        @param {dict} mapping - mapping.josn文件对应的字典

        @return {bool} - 处理结果
        """
        try:
            _fix_str = "item {\n    id: %d\n    name: '%s'\n}"
            _list = []

            # 按int进行排序
            _class_int = sorted(mapping['class_int'].items(), key=lambda kv: (kv[1], kv[0]))
            for _item in _class_int:
                _id = _item[1]
                _name = mapping['class'][_item[0]]
                _list.append(_fix_str % (_id, _name))

            # 保存到文件中
            FileTool.create_dir(save_path, exist_ok=True)
            with open(os.path.join(save_path, 'labelmap.pbtxt'), 'wb') as f:
                f.write(str.encode('\n\n'.join(_list), encoding='utf-8'))

            return True
        except:
            print('create_pbtxt error: \r\n%s' % (traceback.format_exc(),))
            return False

    @classmethod
    def labelimg_to_tfrecord(cls, input_path: str, output_file: str, num_per_file: int = None,
                             class_to_int_fun=None, use_mapping: bool = False, mapping: dict = None,
                             copy_img_path=None):
        """
        将LabelImg标注后的图片目录转换为TFRecord格式文件

        @param {str} input_path - 输入图片清单目录，注意labelimg标注的xml与图片文件在一个目录中
        @param {str} output_file - 输出的TFRecord格式文件路径（含文件名，例如xx.record）
        @param {int} num_per_file=None - 拆分每个TFRecord文件的文件大小
        @param {function} class_to_int_fun=None - 将分类名转换为int的函数
            如果传None代表类名为数字，可以直接将类名转换为数字
        @param {bool} use_mapping=False - 是否使用mapping.json数据处理转换
        @param {dict} mapping=None - mapping.json字典
        @param {str} copy_img_path=None - 如果传值了则复制对应的图片到对应目录

        @returns {iter_list} - 通过yield返回的处理进度信息清单
            [总文件数int, 当前已处理文件数int, 是否成功]
        """
        try:
            # 遍历所有文件夹，获取需要处理的文件数量
            _file_list = cls._get_labelimg_annotation_file_list(input_path)
            _total = len(_file_list)
            _deal_num = 0

            # 先返回进度情况
            if _total == 0:
                yield [_deal_num, _total, True, {}]
                return

            # 基础变量
            _output_file = output_file
            _current_package = 1  # 当前包序号
            _package_file_num = 0  # 当前包文件数量
            _total_pkg_num = 1  # 包总数量
            if num_per_file is not None:
                _total_pkg_num = math.ceil(_total / num_per_file)
                _output_file = '%s-%.5d-of-%.5d' % (output_file, _current_package, _total_pkg_num)

            # 创建文件夹
            FileTool.create_dir(os.path.split(_output_file)[0], exist_ok=True)

            if copy_img_path is not None:
                FileTool.create_dir(copy_img_path, exist_ok=True)

            # 标签的统计信息
            _flags_count = dict()

            # TFRecordWriter
            _writer = tf.io.TFRecordWriter(_output_file)

            # 遍历文件进行处理
            _writer_closed = False
            for _file in _file_list:
                # 当前进展
                yield [_deal_num, _total, True, _flags_count]

                # 写入当前文件
                _tf_example = cls._create_labelimg_tf_example(
                    _file, class_to_int_fun=class_to_int_fun, use_mapping=use_mapping, mapping=mapping,
                    copy_img_path=copy_img_path, flags_count=_flags_count
                )
                _deal_num += 1

                if _tf_example is not None:
                    _writer.write(_tf_example.SerializeToString())
                    _package_file_num += 1
                else:
                    # 没有找到写入信息，直接下一个
                    continue

                if num_per_file is not None:
                    if _package_file_num >= num_per_file:
                        # 一个文件数据已写够
                        _writer.close()
                        if _current_package >= _total_pkg_num:
                            # 已经是最后一个包
                            _writer_closed = True
                            break
                        else:
                            # 要处理下一个包
                            _current_package += 1
                            _package_file_num = 0
                            _output_file = '%s-%.5d-of-%.5d' % (output_file,
                                                                _current_package, _total_pkg_num)
                            _writer = tf.io.TFRecordWriter(_output_file)

            # 最后的保存
            if not _writer_closed:
                _writer.close()

            # 判断是否要修改文件名(实际数量少于预期数量)
            if _current_package < _total_pkg_num:
                for _index in range(1, _current_package + 1):
                    os.rename(
                        '%s-%.5d-of-%.5d' % (output_file,
                                             _index, _total_pkg_num),
                        '%s-%.5d-of-%.5d' % (output_file,
                                             _index, _current_package),
                    )

            # 返回结果
            yield [_total, _total, True, _flags_count]
        except:
            print('labelimg_to_tfrecord error: %s\r\n%s' % (input_path, traceback.format_exc()))
            yield [-1, -1, False, {}]

    @classmethod
    def labelimg_flags_count(cls, input_path: str, mapping: dict):
        """
        统计指定目录中的labelimg标记对应标签的数量

        @param {str} input_path - 要统计的目录
        @param {dict} mapping - mapping.json的字典

        @returns {iter_list} - 通过yield返回的处理进度信息清单
            [总文件数int, 当前已处理文件数int, 是否成功, 统计结果字典(标签名, 数量)]
        """
        try:
            # 遍历所有文件夹，获取需要处理的文件数量
            _file_list = cls._get_labelimg_annotation_file_list(input_path)
            _total = len(_file_list)
            _deal_num = 0
            _flags_count = dict()

            # 先返回进度情况
            if _total == 0:
                yield [_deal_num, _total, True, _flags_count]
                return

            # 遍历文件进行处理
            for _file in _file_list:
                # 当前进展
                yield [_deal_num, _total, True, _flags_count]

                # 统计当前文件
                _tree = ET.parse(_file)
                _root = _tree.getroot()

                _image_file = os.path.join(
                    os.path.split(_file)[0], FileTool.get_file_name_no_ext(_file) + '.jpg'
                )
                _info_dict = ExtendLib.get_info_dict(_image_file, mapping['info_key_dict'])

                # 逐个标签处理
                for _member in _root.findall('object'):
                    _member_class = _member[0].text
                    if _member_class == mapping['set_by_info']['class_name']:
                        # 需要转换为当前类型
                        if mapping['set_by_info']['info_tag'] in _info_dict.keys():
                            _member_class = _info_dict[mapping['set_by_info']['info_tag']]

                    if _member_class in _flags_count.keys():
                        _flags_count[_member_class] += 1
                    else:
                        _flags_count[_member_class] = 1

                _deal_num += 1

            # 返回结果
            yield [_total, _total, True, _flags_count]
        except:
            print('labelimg_flags_count error: %s\r\n%s' % (input_path, traceback.format_exc()))
            yield [-1, -1, False]

    @classmethod
    def labelimg_copy_flags_pics(cls, input_path: str, output_path: str, use_mapping: bool = False,
                                 mapping: dict = None):
        """
        按类别复制图片和标注文件到指定目录

        @param {str} input_path - 图片路径
        @param {str} output_path - 输出路径
        @param {bool} use_mapping=False - 是否使用mapping处理映射
        @param {dict} mapping=None - mapping.josn字典

        @returns {iter_list} - 通过yield返回的处理进度信息清单
            [总文件数int, 当前已处理文件数int, 是否成功]
        """
        try:
            # 遍历所有文件夹，获取需要处理的文件数量
            _file_list = cls._get_labelimg_annotation_file_list(input_path)
            _total = len(_file_list)
            _deal_num = 0

            # 先返回进度情况
            if _total == 0:
                yield [_deal_num, _total, True]
                return

            # 创建复制文件夹
            FileTool.create_dir(output_path, exist_ok=True)

            # 遍历处理
            for _file in _file_list:
                # 当前进展
                yield [_deal_num, _total, True]

                # 逐个标注文件进行处理
                _tree = ET.parse(_file)
                _root = _tree.getroot()

                _annotations = dict()
                _annotations['filename'] = _root.find('filename').text
                _annotations['file_path'] = os.path.join(
                    os.path.split(_file)[0], _annotations['filename']
                )

                # 获取信息字典
                _info_dict = ExtendLib.get_info_dict(
                    _annotations['file_path'], mapping['info_key_dict'])

                # 逐个标签处理
                _save_class_path = ''  # 要保存到的分类路径
                _is_copy = False  # 标注是否已复制文件
                _new_xml_name = ''  # 新的xml名
                for _member in _root.findall('object'):
                    _member_class = _member[0].text
                    if use_mapping:
                        # 使用映射处理
                        if _member_class == mapping['set_by_info']['class_name']:
                            # 需要获取真实的信息
                            if mapping['set_by_info']['info_tag'] in _info_dict.keys():
                                _member_class = _info_dict[mapping['set_by_info']['info_tag']]

                                # 变更分类名
                                _member[0].text = _member_class

                        # 过滤不需要的类别
                        if _member_class not in mapping['class_int'].keys():
                            _deal_num += 1
                            continue

                        # 保存分类路径
                        _save_class_path = os.path.join(
                            output_path, mapping['class'][_member_class]
                        )
                    else:
                        # 普通分类
                        _save_class_path = os.path.join(
                            output_path, _member_class
                        )

                    # 复制文件
                    if not _is_copy:
                        # 处理重复文件名
                        _file_name = FileTool.get_file_name_no_ext(_annotations['filename'])
                        _file_ext = FileTool.get_file_ext(_annotations['filename'])
                        _rename_num = 1
                        _new_file_name = '%s.%s' % (_file_name, _file_ext)
                        _new_xml_name = '%s.xml' % (_file_name, )
                        while os.path.exists(os.path.join(_save_class_path, _new_file_name)):
                            _new_file_name = '%s_%d.%s' % (_file_name, _rename_num, _file_ext)
                            _new_xml_name = '%s_%d.xml' % (_file_name, _rename_num)
                            _rename_num += 1

                        # 创建文件夹
                        FileTool.create_dir(_save_class_path, exist_ok=True)
                        shutil.copyfile(
                            _annotations['file_path'],
                            os.path.join(_save_class_path, _new_file_name)
                        )

                        # 修改xml里面的文件名和文件路径
                        _root.find('filename').text = _new_file_name
                        _root.find('path').text = os.path.join(
                            _save_class_path, _new_file_name)

                        _is_copy = True

                if _is_copy:
                    # 有修改xml内容
                    _tree.write(
                        os.path.join(_save_class_path, _new_xml_name),
                        encoding='utf-8', method="xml",
                        xml_declaration=None
                    )

                # 继续循环处理
                _deal_num += 1

            # 返回结果
            yield [_total, _total, True]
        except:
            print('labelimg_copy_flags_pics error: %s\r\n%s' % (input_path, traceback.format_exc()))
            yield [-1, -1, False]

    @classmethod
    def labelimg_rename_filename(cls, path: str, fix_len: int = 10):
        """
        重名名labelimg对应目录下的文件名（图片文件和标注文件同步修改）

        @param {str} path - 要修改文件名的路径
        @param {int} fix_len=10 - 文件名长度
        """
        _path = os.path.realpath(path)
        _files = FileTool.get_filelist(path=_path, is_fullname=False)
        _index = 1
        for _file in _files:
            _file_ext = FileTool.get_file_ext(_file)
            if _file_ext == 'xml':
                # 标签文件不处理
                continue

            _file_no_ext = FileTool.get_file_name_no_ext(_file)
            # 获取最新的文件名
            while True:
                _new_name = StringTool.fill_fix_string(str(_index), fix_len, '0', left=True)
                _new_file = _new_name + '.' + _file_ext
                _index += 1
                if os.path.exists(os.path.join(path, _new_file)):
                    # 文件名已存在
                    _index += 1
                    continue

                # 文件名不存在，跳出循环
                break

            # 修改文件名
            os.rename(
                os.path.join(_path, _file), os.path.join(_path, _new_file)
            )
            if os.path.exists(os.path.join(_path, _file_no_ext + '.xml')):
                # 需要修改标签文件
                _xml_file = _new_name + '.xml'
                os.rename(
                    os.path.join(_path, _file_no_ext + '.xml'), os.path.join(_path, _xml_file)
                )

                # 修改标签文件内容
                _tree = ET.parse(os.path.join(_path, _xml_file))
                _root = _tree.getroot()
                _root.find('filename').text = _new_file
                _root.find('path').text = os.path.join(_path, _new_file)
                _tree.write(
                    os.path.join(_path, _xml_file),
                    encoding='utf-8', method="xml",
                    xml_declaration=None
                )

    @classmethod
    def labelimg_pic_deal(cls, path: str):
        """
        TFRecord图片兼容处理
        1.删除位深不为RGB三通道的图片
        （解决image_size must contain 3 elements[4]报错）
        2.转换图片格式为jpg
        3.检查xml文件的文件名和路径是否正确

        @param {str} path - 要处理的路径
        """
        _path = os.path.realpath(path)
        # 遍历所有子目录
        _sub_dirs = FileTool.get_dirlist(path=_path, is_fullpath=True)
        for _dir in _sub_dirs:
            # 递归删除子目录的信息
            cls.labelimg_pic_deal(_dir)

        # 检查自己目录下的图片
        _files = FileTool.get_filelist(path=_path, is_fullname=False)
        for _file in _files:
            _file_ext = FileTool.get_file_ext(_file)
            if _file_ext == 'xml':
                # 标签文件不处理
                continue

            _img_file = os.path.join(_path, _file)
            _file_no_ext = FileTool.get_file_name_no_ext(_file)

            if _file_ext in ('png', 'gif'):
                # 转换图片格式
                _fp = open(_img_file, 'rb')
                _img = Image.open(_fp)
                _rgb_im = _img.convert('RGB')

                _rgb_im.save(os.path.join(_path, _file_no_ext + '.jpg'))
                _fp.close()

                # 删除原文件，修改xml中的文件名
                FileTool.remove_file(_img_file)
                _xml_file = os.path.join(_path, _file_no_ext + '.xml')
                if os.path.exists(_xml_file):
                    _tree = ET.parse(os.path.join(_path, _xml_file))
                    _root = _tree.getroot()
                    _root.find('filename').text = _file_no_ext + '.jpg'
                    _root.find('path').text = os.path.join(_path, _file_no_ext + '.jpg')
                    _tree.write(
                        os.path.join(_path, _xml_file),
                        encoding='utf-8', method="xml",
                        xml_declaration=None
                    )

                # 修改文件名变量
                _img_file = os.path.join(_path, _file_no_ext + '.jpg')

            # 打开图片判断位深
            _fp = open(_img_file, 'rb')
            _img = Image.open(_fp)
            if _img.mode != 'RGB':
                # 需要删除掉
                _fp.close()
                _xml_file = os.path.join(_path, FileTool.get_file_name_no_ext(_file) + '.xml')
                print('delete %s' % _img_file)
                FileTool.remove_file(_img_file)
                if os.path.exists(_xml_file):
                    FileTool.remove_file(_xml_file)
            else:
                _fp.close()

            # 检查xml文件
            _xml_file = os.path.join(_path, _file_no_ext + '.xml')
            if os.path.exists(_xml_file):
                _tree = ET.parse(os.path.join(_path, _xml_file))
                _root = _tree.getroot()
                if _root.find('filename').text != _file_no_ext + '.jpg' or os.path.split(
                    _root.find('path').text
                )[0] != _path:
                    _root.find('filename').text = _file_no_ext + '.jpg'
                    _root.find('path').text = os.path.join(_path, _file_no_ext + '.jpg')
                    _tree.write(
                        os.path.join(_path, _xml_file),
                        encoding='utf-8', method="xml",
                        xml_declaration=None
                    )

    @classmethod
    def labelimg_crop_pic_by_flags(cls, path: str, dest_path: str, copy_no_flag_pic: bool = True,
                                   with_sub_dir: bool = True, fix_len: int = 10):
        """
        根据标注进行图片截图处理

        @param {str} path - 需要处理的目录
        @param {str} dest_path - 截图图片存放目录
        @param {bool} copy_no_flag_pic=True - 直接复制没有标注的图片
        @param {bool} with_sub_dir=True - 是否按原目录结构存储图片
        @param {int} fix_len=10 - 图片重命名的文件名长度

        @returns {iter_list} - 通过yield返回的处理进度信息清单
            [总文件数int, 当前已处理文件数int, 是否成功]
        """
        try:
            # 获取所有要处理的图片清单
            _file_list = cls._get_pic_file_list(path)
            _total = len(_file_list)
            _deal_num = 0

            # 先返回进度情况
            if _total == 0:
                yield [_deal_num, _total, True]
                return

            # 创建复制文件夹
            FileTool.create_dir(dest_path, exist_ok=True)

            # 遍历处理
            _rename_index = 1
            _src_path = os.path.realpath(path)
            _dest_path = os.path.realpath(dest_path)
            for _file in _file_list:
                # 当前进展
                yield [_deal_num, _total, True]

                # 路径处理
                _file_path, _filename = os.path.split(_file)
                if with_sub_dir:
                    # 创建子目录
                    _dest_path = os.path.join(
                        os.path.realpath(dest_path),
                        os.path.realpath(_file_path)[len(_src_path):].strip('/\\')
                    )
                    FileTool.create_dir(_dest_path, exist_ok=True)

                # 获取标注文件
                _ext = FileTool.get_file_ext(_filename)
                _xml_file = os.path.join(
                    _file_path,
                    _filename[0: -len(_ext)] + 'xml'
                )

                if not os.path.exists(_xml_file):
                    # 标注文件不存在
                    if copy_no_flag_pic:
                        # 直接复制文件
                        shutil.copy(
                            _file, os.path.join(
                                _dest_path,
                                StringTool.fill_fix_string(
                                    str(_rename_index), fix_len, '0') + '.' + _ext
                            )
                        )
                        _rename_index += 1

                    # 下一个
                    _deal_num += 1
                    continue

                # 将图片放入内存
                with open(_file, 'rb') as _fid:
                    _file_bytes = _fid.read()
                    _image = Image.open(BytesIO(_file_bytes))

                # 处理标注
                _tree = ET.parse(_xml_file)
                _root = _tree.getroot()

                for _member in _root.findall('object'):
                    # 逐个标注进行处理
                    _crop_image = _image.crop((
                        int(_member[4][0].text),
                        int(_member[4][1].text),
                        int(_member[4][2].text),
                        int(_member[4][3].text)
                    ))

                    _crop_image.save(
                        os.path.join(
                            _dest_path,
                            StringTool.fill_fix_string(
                                str(_rename_index), fix_len, '0') + '.' + _ext
                        ),
                        format='JPEG'
                    )

                    _rename_index += 1

                # 下一个
                _deal_num += 1

            # 返回结果
            yield [_total, _total, True]
        except:
            print('labelimg_crop_pic_by_flags error: %s\r\n%s' % (path, traceback.format_exc()))
            yield [-1, -1, False]

    #############################
    # 内部函数
    #############################

    @classmethod
    def _get_keys_by_value(cls, d: dict, value):
        """
        根据字典的值获取key

        @param {dict} d - 字典
        @param {str} value - 值
        """
        for _key in d.keys():
            if d[_key] == value:
                return _key

        # 找不到
        return None

    @classmethod
    def _get_labelimg_annotation_file_list(cls, input_path: str) -> list:
        """
        获取要处理的LabelImg标注文件清单

        @param {str} input_path - 起始目录

        @returns {list} - 返回文件清单
        """
        _list = []

        # 先获取当前目录下的所有xml文件
        for _file in FileTool.get_filelist(input_path, regex_str=r'.*\.xml$'):
            _pic_file = _file[0:-3] + 'jpg'
            if os.path.exists(_pic_file):
                _list.append(_file)

        # 获取子目录
        for _dir in FileTool.get_dirlist(input_path):
            _temp_list = cls._get_labelimg_annotation_file_list(_dir)
            _list.extend(_temp_list)

        return _list

    @classmethod
    def _create_labelimg_tf_example(cls, annotation_file: str, class_to_int_fun=None,
                                    use_mapping: bool = False,
                                    copy_img_path: str = None,
                                    mapping: dict = None,
                                    flags_count: dict = {}) -> tf.train.Example:
        """
        生成指定标注的Example对象

        @param {str} annotation_file - 标注xml文件
        @param {function} class_to_int_fun=None - 将分类名转换为int的函数
            如果传None代表类名为数字，可以直接将类名转换为数字
        @param {bool} use_mapping=False - 是否使用mapping.json数据处理转换
        @param {str} copy_img_path=None - 如果传值了则复制对应的图片到对应目录
        @param {dict} mapping=None - mapping.json字典
        @param {dict} flags_count={} - 标签统计信息

        @returns {tf.train.Example} - Example对象
        """
        # 获取未知类对应的int值
        _other_class_int = -1
        for _key in mapping['class'].keys():
            if mapping['class'][_key] == 'other':
                _other_class_int = mapping['class_int'][_key]
                break

        # 获取标注文件信息
        _tree = ET.parse(annotation_file)
        _root = _tree.getroot()
        _annotations = dict()
        _annotations['filename'] = _root.find('filename').text
        _annotations['file_path'] = os.path.join(
            os.path.split(annotation_file)[0], _annotations['filename']
        )
        _annotations['width'] = int(_root.find('size')[0].text)
        _annotations['height'] = int(_root.find('size')[1].text)

        # 图片文件二进制处理
        with tf.io.gfile.GFile(_annotations['file_path'], 'rb') as fid:
            _encoded_jpg = fid.read()
        _encoded_jpg_io = io.BytesIO(_encoded_jpg)
        _image = Image.open(_encoded_jpg_io)
        _width, _height = _image.size

        # 处理信息要素
        _filename = _annotations['filename'].encode('utf8')
        _image_format = b'jpg'
        _xmins = []
        _xmaxs = []
        _ymins = []
        _ymaxs = []
        _classes_text = []
        _classes = []

        # 获取信息字典
        _info_dict = ExtendLib.get_info_dict(
            _annotations['file_path'], mapping['info_key_dict'])

        # 遍历字典信息获取要处理的标注
        _tag_list = list()
        for _member in _root.findall('object'):
            _member_class = _member[0].text
            _class_int = 0
            if use_mapping:
                # 使用mapping.json类型转换
                if _member_class == mapping['set_by_info']['class_name']:
                    # 需要获取真实的信息
                    if mapping['set_by_info']['info_tag'] in _info_dict.keys():
                        _member_class = _info_dict[mapping['set_by_info']['info_tag']]

                if _member_class in mapping['class_int'].keys():
                    _class_int = mapping['class_int'][_member_class]
                    _member_class = mapping['class'][_member_class]
                else:
                    # 不在处理清单的标签
                    if mapping['unknow_to_other'] and _other_class_int != -1:
                        # 将类型转为未知
                        _member_class = 'other'
                        _class_int = _other_class_int
                    else:
                        # 不进行处理
                        if _member_class in flags_count.keys():
                            flags_count[_member_class] -= 1
                        else:
                            flags_count[_member_class] = -1
                        continue
            else:
                if class_to_int_fun is None:
                    _class_int = int(_member_class)
                else:
                    _class_int = class_to_int_fun(_member_class)

            _tag_info = {
                'class': _member_class,
                'class_int': _class_int,
                'xmin': int(_member[4][0].text),
                'ymin': int(_member[4][1].text),
                'xmax': int(_member[4][2].text),
                'ymax': int(_member[4][3].text)
            }

            _tag_info['size'] = (_tag_info['xmax'] - _tag_info['xmin']) * \
                (_tag_info['ymax'] - _tag_info['ymin'])

            _tag_list.append(_tag_info)

        # 按标注的size反向排序
        _tag_list.sort(key=lambda x: x['size'], reverse=True)

        # 从后往前遍历看是否要删除标注
        _end_index = len(_tag_list) - 1  # 从后往前的遍历索引
        while _end_index > 0:
            _start_index = 0  # 从前往后的遍历索引
            while _start_index < _end_index:
                _large = _tag_list[_start_index]  # 大面积标注
                _small = _tag_list[_end_index]  # 小面积标注

                if _large['class'] not in mapping['ignore_inner'].keys():
                    # 外部标注无需忽略内部标注
                    _start_index += 1
                    continue

                if mapping['ignore_inner'][_large['class']] == 'other' and _small['class'] != 'other':
                    # 内部标注不是other标注
                    _start_index += 1
                    continue

                if _large['xmin'] <= _small['xmin'] and _large['xmax'] >= _small['xmax'] and _large['ymin'] <= _small['ymin'] and _large['ymax'] >= _small['ymax']:
                    if _large['size'] != _small['size']:
                        # 确保两个框不是完全一样, 是包含关系，前面已排除不能忽略的情况，直接删除
                        _tag_list.pop(_end_index)
                        break

                # 从上往下找下一个
                _start_index += 1

            # 从下网上继续进行判断
            _end_index -= 1

        # 留下来的逐个标签处理
        for _tag in _tag_list:
            _xmins.append(_tag['xmin'] / _width)
            _xmaxs.append(_tag['xmax'] / _width)
            _ymins.append(_tag['ymin'] / _height)
            _ymaxs.append(_tag['ymax'] / _height)
            _classes_text.append(_tag['class'].encode('utf8'))
            _classes.append(_tag['class_int'])
            if _tag['class'] in flags_count.keys():
                flags_count[_tag['class']] += 1
            else:
                flags_count[_tag['class']] = 1

        if len(_classes_text) == 0:
            # 没有找到适用的内容，返回None
            return None
        else:
            # 复制文件
            # print(_annotations['file_path'])
            if copy_img_path is not None:
                shutil.copyfile(
                    annotation_file,
                    os.path.join(copy_img_path, os.path.split(annotation_file)[1])
                )
                shutil.copyfile(
                    _annotations['file_path'],
                    os.path.join(copy_img_path, _annotations['filename'])
                )

        tf_example = tf.train.Example(features=tf.train.Features(feature={
            'image/height': dataset_util.int64_feature(_height),
            'image/width': dataset_util.int64_feature(_width),
            'image/filename': dataset_util.bytes_feature(_filename),
            'image/source_id': dataset_util.bytes_feature(_filename),
            'image/encoded': dataset_util.bytes_feature(_encoded_jpg),
            'image/format': dataset_util.bytes_feature(_image_format),
            'image/object/bbox/xmin': dataset_util.float_list_feature(_xmins),
            'image/object/bbox/xmax': dataset_util.float_list_feature(_xmaxs),
            'image/object/bbox/ymin': dataset_util.float_list_feature(_ymins),
            'image/object/bbox/ymax': dataset_util.float_list_feature(_ymaxs),
            'image/object/class/text': dataset_util.bytes_list_feature(_classes_text),
            'image/object/class/label': dataset_util.int64_list_feature(_classes),
        }))

        return tf_example

    @classmethod
    def _get_pic_file_list(cls, input_path: str) -> list:
        """
        获取制定目录下的所有图片文件清单

        @param {str} input_path - 要处理的目录

        @returns {list} - 文件清单列表
        """
        _list = []

        # 先获取当前目录下的所有xml文件
        for _file in FileTool.get_filelist(input_path, is_fullname=True):
            _ext = FileTool.get_file_ext(_file)
            if _ext.lower() in ('jpg', 'jpeg'):
                _list.append(_file)

        # 获取子目录
        for _dir in FileTool.get_dirlist(input_path):
            _temp_list = cls._get_pic_file_list(_dir)
            _list.extend(_temp_list)

        return _list


class TFObjectDetect(object):
    """
    物体识别处理类
    """

    def __init__(self, auto_label: dict, mapping: dict, base_path: str):
        """
        物体识别构造函数

        @param {dict} auto_label - 自动标注参数配置
        @param {dict} mapping - mapping.json字典
        @param {str} base_path - 程序启动的路径
        """
        self.auto_label = auto_label
        self.mapping = mapping
        self.graphs = list()
        for _key in self.auto_label.keys():
            if not self.auto_label[_key]['enable']:
                # 没有启动
                continue

            # 装载物理识别模型
            _graph = {
                'key': _key,
            }
            _pb_file = os.path.join(base_path, self.auto_label[_key]['frozen_graph'])

            _detection_graph = tf.Graph()
            with _detection_graph.as_default():
                _od_graph_def = tf.GraphDef()
                with tf.gfile.GFile(_pb_file, 'rb') as _fid:
                    _serialized_graph = _fid.read()
                    _od_graph_def.ParseFromString(_serialized_graph)
                    tf.import_graph_def(_od_graph_def, name='')

                _graph['session'] = tf.Session(graph=_detection_graph)

            # Input tensor is the image
            _graph['image_tensor'] = _detection_graph.get_tensor_by_name('image_tensor:0')
            # Output tensors are the detection boxes, scores, and classes
            # Each box represents a part of the image where a particular object was detected
            _graph['detection_boxes'] = _detection_graph.get_tensor_by_name('detection_boxes:0')
            # Each score represents level of confidence for each of the objects.
            # The score is shown on the result image, together with the class label.
            _graph['detection_scores'] = _detection_graph.get_tensor_by_name('detection_scores:0')
            _graph['detection_classes'] = _detection_graph.get_tensor_by_name('detection_classes:0')
            # Number of objects detected
            _graph['num_detections'] = _detection_graph.get_tensor_by_name('num_detections:0')

            # 添加到模型列表中
            self.graphs.append(_graph)

    def detect_object(self, image_file: str, shapes: list):
        """
        对指定图片进行物体识别

        @param {str} image_file - 要识别的图片
        @param {list} shapes - 已有的形状

        @returns {list} - 返回匹配上的shape列表
        """
        _object_list = list()
        if len(self.graphs) == 0:
            return _object_list

        _image = Image.open(image_file)
        _image_np = self._load_image_into_numpy_array(_image)
        _image_np_expanded = np.expand_dims(_image_np, axis=0)

        for _graph in self.graphs:
            # 遍历每个识别模型图执行处理
            # Perform the actual detection by running the model with the image as input
            (_boxes, _scores, _classes, _num) = _graph['session'].run(
                [_graph['detection_boxes'], _graph['detection_scores'],
                    _graph['detection_classes'], _graph['num_detections']],
                feed_dict={_graph['image_tensor']: _image_np_expanded})

            _np_scores = np.squeeze(_scores)
            _np_boxes = np.squeeze(_boxes)
            _np_classes = np.squeeze(_classes)
            _index = 0

            _min_distance = self.auto_label[_graph['key']]['min_distance']
            _min_score = self.auto_label[_graph['key']]['min_score']
            _class_int = self.mapping[_graph['key']]['class_int']

            _x_min_distance = int(_image.size[0] * _min_distance)
            _y_min_distance = int(_image.size[1] * _min_distance)
            for _score in _np_scores:
                if _score >= _min_score:
                    # 折算为像素的框
                    _ymin = int(_np_boxes[_index][0] * _image.size[1])
                    _xmin = int(_np_boxes[_index][1] * _image.size[0])
                    _ymax = int(_np_boxes[_index][2] * _image.size[1])
                    _xmax = int(_np_boxes[_index][3] * _image.size[0])
                    _points = [(_xmin, _ymin), (_xmax, _ymin), (_xmax, _ymax), (_xmin, _ymax)]

                    # 标签
                    _label = TFRecordCreater._get_keys_by_value(
                        _class_int, int(_np_classes[_index]))

                    # 形状
                    _shape = [_label, _points, None, None, False]

                    _same = False
                    for _exists_shape in shapes:
                        if self._compare_shapes(_shape, _exists_shape, _x_min_distance, _y_min_distance):
                            # 有其中一个相同
                            _same = True
                            break

                    if not _same:
                        _shape[0] = 'auto_%s_%s' % (_score, _label)
                        _object_list.append(_shape)

                _index += 1

        return _object_list

    #############################
    # 内部函数
    #############################
    def _load_image_into_numpy_array(self, image):
        """
        将图片转换为numpy数组
        """
        (im_width, im_height) = image.size
        return np.array(image.getdata()).reshape((im_height, im_width, 3)).astype(np.uint8)

    def _compare_shapes(self, shape1: list, shape2: list, x_min_distance: int, y_min_distance: int) -> bool:
        """
        比较两个形状

        @param {list} shape1 - 形状1
        @param {list} shape2 - 形状2
        @param {int} x_min_distance - x方向最小距离
        @param {int} y_min_distance - y方向最小距离

        @returns {bool} - 相同返回True，不同返回False
        """
        if shape1[0] != shape2[0]:
            # 不是同一个分类
            return False

        _xmin1 = shape1[1][0][0]
        _ymin1 = shape1[1][0][1]
        _xmax1 = shape1[1][2][0]
        _ymax1 = shape1[1][2][1]
        _xmin2 = shape2[1][0][0]
        _ymin2 = shape2[1][0][1]
        _xmax2 = shape2[1][2][0]
        _ymax2 = shape2[1][2][1]

        if _xmin1 <= _xmin2 and _ymin1 <= _ymin2 and _xmax1 >= _xmax2 and _ymax1 >= _ymax2:
            # shape1 包含 shape2
            return True

        if _xmin1 >= _xmin2 and _ymin1 >= _ymin2 and _xmax1 <= _xmax2 and _ymax1 <= _ymax2:
            # shape2 包含 shape1
            return True

        if abs(_xmin1 - _xmin2) > x_min_distance or abs(_ymin1 - _ymin2) > y_min_distance or abs(_xmax1 - _xmax2) > x_min_distance or abs(_ymax1 - _ymax2) > y_min_distance:
            # 其中有一个边的距离超过最小距离
            return False

        # 距离相近
        return True


if __name__ == '__main__':
    # 当程序自己独立运行时执行的操作
    pass
