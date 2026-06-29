# -*- coding: utf-8 -*-

# ***********************************************************************
# Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot.
# WeChatBot is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# WeChatBot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with WeChatBot.  If not, see <http://www.gnu.org/licenses/>.
# ***********************************************************************

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, Response
import re
import ast
import os
import subprocess
import psutil
import openai
import tempfile
import shutil
from filelock import FileLock
from functools import wraps
import webbrowser
from threading import Timer
import logging
from queue import Queue, Empty
import time
import json
import sqlite3
from datetime import datetime, timedelta
import knowledge_base as kb

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def hide_api_key(api_key):
    """
    隐藏API Key，只显示前4位和后4位，中间用*替代
    """
    if not api_key or len(api_key) <= 8:
        return api_key  # 太短的key不处理
    
    # 显示前4位和后4位，中间用*替代
    return api_key[:4] + '*' * max(4, len(api_key) - 8) + api_key[-4:]

def is_hidden_api_key(api_key):
    """
    检查API Key是否是隐藏版本
    """
    return api_key and '*' in api_key

def safe_type_convert(value, target_type, default_value=None, field_name=""):
    """
    安全的类型转换函数，防止整数转换为字符串
    
    Args:
        value: 要转换的值
        target_type: 目标类型 (int, float, bool)
        default_value: 转换失败时的默认值
        field_name: 字段名，用于日志记录
    
    Returns:
        转换后的值或默认值
    """
    try:
        str_value = str(value).strip()
        
        if target_type == int:
            if str_value and str_value.isdigit():
                return int(str_value)
            elif str_value == '':
                return 0 if default_value is None else default_value
            else:
                if field_name:
                    app.logger.warning(f"配置项 {field_name} 的值 '{value}' 包含非数字字符，使用默认值。")
                return default_value if default_value is not None else 0
                
        elif target_type == float:
            if str_value:
                import re
                if re.match(r'^-?\d+(\.\d+)?$', str_value):
                    return float(str_value)
                else:
                    if field_name:
                        app.logger.warning(f"配置项 {field_name} 的值 '{value}' 不是有效的数字格式，使用默认值。")
                    return default_value if default_value is not None else 0.0
            else:
                return 0.0 if default_value is None else default_value
                
        elif target_type == bool:
            return str_value.lower() in ('on', 'true', '1', 'yes')
            
    except (ValueError, TypeError) as e:
        if field_name:
            app.logger.warning(f"配置项 {field_name} 类型转换失败: {e}，使用默认值。")
        return default_value if default_value is not None else (0 if target_type == int else 0.0 if target_type == float else False)
    
    return value

def validate_config_types(config_path):
    """
    验证config.py中的数据类型是否正确
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查是否有字符串形式的数字
        import re
        
        # 查找可能的问题配置项
        issues = []
        
        # 检查应该是整数但被保存为字符串的配置项
        int_fields = ['MAX_GROUPS', 'MAX_TOKEN', 'QUEUE_WAITING_TIME', 'EMOJI_SENDING_PROBABILITY',
                     'REPLY_MAX_SEGMENTS', 'REPLY_MAX_TOTAL_CHARS', 'KNOWLEDGE_TOP_K', 'KNOWLEDGE_MAX_CONTEXT_CHARS', 'KNOWLEDGE_MIN_SCORE',
                     'MAX_MESSAGE_LOG_ENTRIES', 'MAX_MEMORY_NUMBER', 'PORT', 'ONLINE_API_MAX_TOKEN',
                     'REQUESTS_TIMEOUT', 'MAX_WEB_CONTENT_LENGTH', 'RESTART_INACTIVITY_MINUTES',
                     'GROUP_CHAT_RESPONSE_PROBABILITY', 'ASSISTANT_MAX_TOKEN']
        
        # 检查应该是浮点数但被保存为字符串的配置项  
        float_fields = ['TEMPERATURE', 'MOONSHOT_TEMPERATURE', 'MIN_COUNTDOWN_HOURS', 'MAX_COUNTDOWN_HOURS',
                       'AVERAGE_TYPING_SPEED', 'RANDOM_TYPING_SPEED_MIN', 'RANDOM_TYPING_SPEED_MAX',
                       'ONLINE_API_TEMPERATURE', 'RESTART_INTERVAL_HOURS', 'ASSISTANT_TEMPERATURE']
        
        for field in int_fields:
            pattern = rf'{field}\s*=\s*[\'"](\d+)[\'"]'
            matches = re.findall(pattern, content)
            if matches:
                issues.append(f"{field} 被保存为字符串 '{matches[0]}'，应为整数 {matches[0]}")
        
        for field in float_fields:
            pattern = rf'{field}\s*=\s*[\'"](\d+\.?\d*)[\'"]'
            matches = re.findall(pattern, content)
            if matches:
                issues.append(f"{field} 被保存为字符串 '{matches[0]}'，应为浮点数 {matches[0]}")
        
        if issues:
            app.logger.warning(f"配置文件类型验证发现问题: {'; '.join(issues)}")
            return False
        
        return True
        
    except Exception as e:
        app.logger.error(f"配置文件类型验证失败: {e}")
        return False

app.secret_key = os.urandom(24).hex()  # 48位十六进制字符串
bot_process = None

# 全局日志队列
log_queue = Queue()

CHAT_CONTEXTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_contexts.json')
CHAT_CONTEXTS_LOCK_FILE = CHAT_CONTEXTS_FILE + '.lock'

last_heartbeat_time = 0  # 上次收到心跳的时间戳
HEARTBEAT_TIMEOUT = 15   # 心跳超时阈值（秒），应大于 bot.py 的 HEARTBEAT_INTERVAL
current_bot_pid = None

def get_chat_context_users():
    """从 chat_contexts.json 读取用户列表 (即顶级键)"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return []
    try:
        with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return list(data.keys())
    except (json.JSONDecodeError, IOError) as e:
        app.logger.error(f"读取 chat_contexts.json 失败: {e}")
        return []

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = parse_config()
    if not config.get('ENABLE_LOGIN_PASSWORD', False):
        return redirect(url_for('index'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        stored_pwd = config.get('LOGIN_PASSWORD', '')
        
        if password == stored_pwd:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="密码错误")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        config = parse_config()
        if config.get('ENABLE_LOGIN_PASSWORD', False):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/start_bot', methods=['POST'])
def start_bot():
    global bot_process
    if bot_process is None or bot_process.poll() is not None:
        # 如果目录下存在 user_timers.json 则删除
        user_timers_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_timers.json')
        if os.path.exists(user_timers_path):
            try:
                os.remove(user_timers_path)
            except Exception as e:
                app.logger.warning(f"重置主动消息定时器失败: {e}")

        bot_dir = os.path.dirname(os.path.abspath(__file__))
        
        bot_py = os.path.join(bot_dir, 'bot.py')
        bot_exe = os.path.join(bot_dir, 'bot.exe')
        
        if os.path.exists(bot_py):
            cmd = ['python', bot_py]
        elif os.path.exists(bot_exe):
            cmd = [bot_exe]
        else:
            return {'error': 'No bot executable found'}, 404

        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        bot_process = subprocess.Popen(
            cmd,
            creationflags=creation_flags
        )
    return {'status': 'started'}, 200

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    global bot_process, last_heartbeat_time, current_bot_pid
    # 检查状态时，也考虑 current_bot_pid 是否指示有活跃进程
    is_considered_running = False
    if bot_process and bot_process.poll() is None:
        is_considered_running = True
    elif (time.time() - last_heartbeat_time) < HEARTBEAT_TIMEOUT and current_bot_pid is not None:
        try:
            if psutil.pid_exists(current_bot_pid): # 确保PID对应的进程还存在
                 is_considered_running = True
        except Exception: # psutil.pid_exists 可能会抛出异常，例如权限问题
            pass

    if not is_considered_running:
        app.logger.info("尝试停止机器人，但根据进程对象和心跳判断，机器人似乎已停止。")
        # 即使如此，也调用stop_bot_process来清理状态
        stop_bot_process(pid_to_kill=current_bot_pid if current_bot_pid else (bot_process.pid if bot_process else None))
        return {'status': 'stopped'}, 200
    else:
        pid_from_flask_process = bot_process.pid if bot_process else None
        # 优先使用 current_bot_pid，因为它更可能是最新的
        # 如果 current_bot_pid 和 flask 记录的 pid 不同，且 flask 的 pid 进程也存在，都尝试杀掉
        pids_to_attempt_kill = set()
        if current_bot_pid:
            pids_to_attempt_kill.add(current_bot_pid)
        if pid_from_flask_process:
            pids_to_attempt_kill.add(pid_from_flask_process)

        app.logger.info(f"准备停止机器人，目标PID(s): {pids_to_attempt_kill}")
        for pid in pids_to_attempt_kill:
            stop_bot_process(pid_to_kill=pid) # 传入要杀死的PID

        # 最终状态由 stop_bot_process 设置 current_bot_pid 和 last_heartbeat_time
        return {'status': 'stopped'}, 200
    
@app.route('/bot_status')
def bot_status():
    global bot_process, last_heartbeat_time, current_bot_pid
    
    process_alive_via_flask_obj = bot_process is not None and bot_process.poll() is None
    heartbeat_is_recent = (time.time() - last_heartbeat_time) < HEARTBEAT_TIMEOUT
    
    # 新增：检查 current_bot_pid 对应的进程是否实际存活
    process_alive_via_current_pid = False
    if current_bot_pid is not None:
        try:
            if psutil.pid_exists(current_bot_pid):
                process_alive_via_current_pid = True 
        except psutil.Error:
            pass

    current_status = "stopped"

    if process_alive_via_flask_obj:
        current_status = "running"
    elif heartbeat_is_recent and process_alive_via_current_pid: # 优先检查通过PID确认的存活
        current_status = "running"
    elif heartbeat_is_recent and not process_alive_via_current_pid and current_bot_pid is not None:
        app.logger.warning(f"Bot status: Heartbeat recent, but PID {current_bot_pid} does not exist. Marking as stopped for now. Last heartbeat: {time.time() - last_heartbeat_time:.1f}s ago")
        current_status = "stopped" # 倾向于保守
    elif heartbeat_is_recent : # 心跳最近，但没有 current_bot_pid 信息 (例如 bot.py 未发送PID)
        current_status = "running" # 保持原逻辑：心跳最近则认为运行

    return {"status": current_status}

@app.route('/submit_config', methods=['POST'])
@login_required
def submit_config():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再保存配置'}), 400
    try:
        if not request.form:
            return jsonify({'error': '空的表单提交'}), 400
        
        current_config_before_update = parse_config()
        old_listen_list_map = {item[0]: item[1] for item in current_config_before_update.get('LISTEN_LIST', [])}

        new_values_for_config_py = {}
        
        # 处理API Key字段的特殊逻辑
        api_key_fields = ['DEEPSEEK_API_KEY', 'MOONSHOT_API_KEY', 'ONLINE_API_KEY', 'ASSISTANT_API_KEY']
        for field in api_key_fields:
            if field in request.form:
                submitted_value = request.form[field].strip()
                if is_hidden_api_key(submitted_value):
                    # 如果提交的是隐藏版本，保持原值不变
                    new_values_for_config_py[field] = current_config_before_update.get(field, '')
                else:
                    # 如果提交的是新值，使用新值
                    new_values_for_config_py[field] = submitted_value

        nicknames_from_form = request.form.getlist('nickname')
        prompt_files_from_form = request.form.getlist('prompt_file')
        
        processed_listen_list = []
        if nicknames_from_form and prompt_files_from_form and len(nicknames_from_form) == len(prompt_files_from_form):
            for nick, pf in zip(nicknames_from_form, prompt_files_from_form):
                nick_stripped = nick.strip()
                pf_stripped = pf.strip()
                if nick_stripped and pf_stripped: 
                    processed_listen_list.append([nick_stripped, pf_stripped])
        new_values_for_config_py['LISTEN_LIST'] = processed_listen_list
        
        new_listen_list_map = {item[0]: item[1] for item in processed_listen_list}
        
        users_whose_prompt_changed = []
        for nickname, new_prompt in new_listen_list_map.items():
            if nickname in old_listen_list_map and old_listen_list_map[nickname] != new_prompt:
                users_whose_prompt_changed.append(nickname)

        boolean_fields = [
            'ENABLE_IMAGE_RECOGNITION', 'ENABLE_EMOJI_RECOGNITION',
            'ENABLE_EMOJI_SENDING', 'ENABLE_AUTO_MESSAGE', 'ENABLE_MEMORY',
            'UPLOAD_MEMORY_TO_AI', 'ENABLE_LOGIN_PASSWORD', 'ENABLE_REMINDERS',
            'ALLOW_REMINDERS_IN_QUIET_TIME', 'USE_VOICE_CALL_FOR_REMINDERS',
            'ENABLE_ONLINE_API', 'SEPARATE_ROW_SYMBOLS', 'ENABLE_REPLY_LENGTH_LIMIT', 'ENABLE_KNOWLEDGE_BASE', 'KNOWLEDGE_AUTO_SEARCH', 'ENABLE_SCHEDULED_RESTART',
            'ENABLE_GROUP_AT_REPLY', 'ENABLE_GROUP_KEYWORD_REPLY','GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY', 'REMOVE_PARENTHESES',
            'ENABLE_ASSISTANT_MODEL', 'USE_ASSISTANT_FOR_MEMORY_SUMMARY',
            'IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE', 'ENABLE_SENSITIVE_CONTENT_CLEARING', 'SAVE_MEMORY_TO_SEPARATE_FILE',
            'ENABLE_TEXT_COMMANDS'
        ]
        for field in boolean_fields:
            new_values_for_config_py[field] = field in request.form

        for key_from_form in request.form:
            if key_from_form in ['nickname', 'prompt_file'] or key_from_form in boolean_fields or key_from_form in api_key_fields:
                continue 

            value_from_form = request.form[key_from_form].strip()
            
            if key_from_form == 'GROUP_KEYWORD_LIST':
                if value_from_form:
                    normalized_value = re.sub(r'，|\s+', ',', value_from_form)
                    keywords_list = [kw.strip() for kw in normalized_value.split(',') if kw.strip()]
                    new_values_for_config_py[key_from_form] = keywords_list
                else:
                    new_values_for_config_py[key_from_form] = []
                continue

            if key_from_form in current_config_before_update:
                original_type_source = current_config_before_update[key_from_form]
                if isinstance(original_type_source, bool):
                    new_values_for_config_py[key_from_form] = (value_from_form.lower() == 'true')
                elif key_from_form in ["MIN_COUNTDOWN_HOURS", "MAX_COUNTDOWN_HOURS", "AVERAGE_TYPING_SPEED", "RANDOM_TYPING_SPEED_MIN", "RANDOM_TYPING_SPEED_MAX", "TEMPERATURE", "MOONSHOT_TEMPERATURE", "ONLINE_API_TEMPERATURE", "ASSISTANT_TEMPERATURE", "RESTART_INTERVAL_HOURS"]:
                    try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value:
                            # 验证是否为有效的数字格式
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                # 如果不是有效数字格式，保留原值
                                new_values_for_config_py[key_from_form] = original_type_source
                                app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已保留旧值。")
                        else:
                            new_values_for_config_py[key_from_form] = 0.0
                    except (ValueError, TypeError) as e: 
                        new_values_for_config_py[key_from_form] = original_type_source 
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, int) or key_from_form in ["GROUP_CHAT_RESPONSE_PROBABILITY", "RESTART_INACTIVITY_MINUTES", "ASSISTANT_MAX_TOKEN", "REPLY_MAX_SEGMENTS", "REPLY_MAX_TOTAL_CHARS", "KNOWLEDGE_TOP_K", "KNOWLEDGE_MAX_CONTEXT_CHARS", "KNOWLEDGE_MIN_SCORE"]:
                    try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 0
                        else:
                            # 如果包含非数字字符，保留原值
                            new_values_for_config_py[key_from_form] = original_type_source
                            app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已保留旧值。")
                    except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, float):
                     try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value:
                            # 验证是否为有效的数字格式
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                # 如果不是有效数字格式，保留原值
                                new_values_for_config_py[key_from_form] = original_type_source
                                app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已保留旧值。")
                        else:
                            new_values_for_config_py[key_from_form] = 0.0
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, list):
                    try:
                        evaluated_list = ast.literal_eval(value_from_form)
                        if isinstance(evaluated_list, list):
                            new_values_for_config_py[key_from_form] = evaluated_list
                        else:
                            new_values_for_config_py[key_from_form] = original_type_source
                            app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 解析后不是列表，已保留旧值。")
                    except:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法解析为列表，已保留旧值。")
                else: 
                    new_values_for_config_py[key_from_form] = value_from_form
            else: 
                if key_from_form == "GROUP_CHAT_RESPONSE_PROBABILITY":
                    try:
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 0
                        else:
                            new_values_for_config_py[key_from_form] = 100
                            app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已设为默认值100。")
                    except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 100
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已设为默认值100。错误: {e}")
                elif key_from_form == "RESTART_INACTIVITY_MINUTES":
                     try:
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 15
                        else:
                            new_values_for_config_py[key_from_form] = 15
                            app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已设为默认值15。")
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 15 
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已设为默认值15。错误: {e}")

                elif key_from_form == "RESTART_INTERVAL_HOURS":
                     try:
                        str_value = str(value_from_form).strip()
                        if str_value:
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                new_values_for_config_py[key_from_form] = 2.0
                                app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已设为默认值2.0。")
                        else:
                            new_values_for_config_py[key_from_form] = 2.0
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 2.0
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已设为默认值2.0。错误: {e}")
                else:
                    new_values_for_config_py[key_from_form] = value_from_form
        
        update_config(new_values_for_config_py)
        
        # 验证配置文件类型正确性
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, 'config.py')
        validate_config_types(config_path)

        if users_whose_prompt_changed:
            with FileLock(CHAT_CONTEXTS_LOCK_FILE):
                try:
                    if os.path.exists(CHAT_CONTEXTS_FILE):
                        with open(CHAT_CONTEXTS_FILE, 'r+', encoding='utf-8') as f:
                            chat_data = json.load(f)
                            modified_chat_data = False
                            for user_to_clear in users_whose_prompt_changed:
                                if user_to_clear in chat_data:
                                    del chat_data[user_to_clear]
                                    modified_chat_data = True
                                    app.logger.info(f"因Prompt文件变更，用户 '{user_to_clear}' 的聊天上下文已清除。")
                            if modified_chat_data:
                                f.seek(0)
                                json.dump(chat_data, f, ensure_ascii=False, indent=4)
                                f.truncate()
                except (json.JSONDecodeError, IOError) as e:
                    app.logger.error(f"清除因Prompt变更导致的聊天上下文时出错: {e}")
                    
        return '', 204 
    except Exception as e:
        app.logger.error(f"配置保存失败: {str(e)}")
        return jsonify({'error': f'配置保存失败: {str(e)}'}), 500

def stop_bot_process(pid_to_kill=None):
    global bot_process, last_heartbeat_time, current_bot_pid
    
    process_killed_successfully = False

    if pid_to_kill:
        try:
            if psutil.pid_exists(pid_to_kill):
                bot_psutil = psutil.Process(pid_to_kill)
                app.logger.info(f"尝试终止PID为 {pid_to_kill} 的机器人进程...")
                bot_psutil.terminate()
                bot_psutil.wait(timeout=5) # 等待进程终止
                app.logger.info(f"通过 terminate 成功停止了PID {pid_to_kill}。")
                process_killed_successfully = True
            else:
                app.logger.info(f"PID {pid_to_kill} 指定的进程不存在。")
                process_killed_successfully = True # 认为已停止
        except psutil.NoSuchProcess:
            app.logger.info(f"尝试终止PID {pid_to_kill} 时，进程已不存在。")
            process_killed_successfully = True # 认为已停止
        except psutil.TimeoutExpired: # psutil.TimeoutExpired
            app.logger.warning(f"Terminate PID {pid_to_kill} 超时，尝试 kill。")
            try:
                if psutil.pid_exists(pid_to_kill): # 再次确认存在
                    bot_psutil_kill = psutil.Process(pid_to_kill)
                    bot_psutil_kill.kill()
                    bot_psutil_kill.wait(timeout=3)
                    app.logger.info(f"通过 kill 成功停止了PID {pid_to_kill}。")
                    process_killed_successfully = True
            except psutil.NoSuchProcess:
                 app.logger.info(f"尝试 kill PID {pid_to_kill} 时，进程已不存在。")
                 process_killed_successfully = True
            except Exception as e_kill:
                app.logger.error(f"Kill PID {pid_to_kill} 失败: {e_kill}")
        except Exception as e:
            app.logger.error(f"停止PID {pid_to_kill} 时发生错误: {e}")

    # 如果被杀死的PID是Flask自己启动的进程，则清空bot_process
    if bot_process and pid_to_kill == bot_process.pid and process_killed_successfully:
        app.logger.info(f"清空 Flask 维护的 bot_process 对象 (原PID: {bot_process.pid})。")
        bot_process = None
    
    # 如果被杀死的PID是当前记录的机器人PID，则清空current_bot_pid
    if current_bot_pid and pid_to_kill == current_bot_pid and process_killed_successfully:
        app.logger.info(f"清空 current_bot_pid (原PID: {current_bot_pid})。")
        current_bot_pid = None

    last_heartbeat_time = 0
    if not current_bot_pid and not bot_process: # 确保如果所有已知进程句柄都清了，才彻底标记
        app.logger.info("所有已知的机器人进程句柄均已清理。重置心跳时间。")
    elif current_bot_pid:
        app.logger.warning(f"调用 stop_bot_process 后，current_bot_pid ({current_bot_pid}) 仍有值。可能存在未完全停止的实例或状态不同步。但心跳已重置。")

@app.route('/bot_heartbeat', methods=['POST'])
def bot_heartbeat():
    global last_heartbeat_time, current_bot_pid
    try:
        last_heartbeat_time = time.time()
        data = request.get_json()
        
        if data and 'pid' in data:
            received_pid = data.get('pid')
            if received_pid and isinstance(received_pid, int):
                if current_bot_pid != received_pid:
                    app.logger.info(f"Bot PID updated via heartbeat: old={current_bot_pid}, new={received_pid}")
                    current_bot_pid = received_pid
            else:
                app.logger.warning(f"Received heartbeat with invalid PID: {received_pid}")
        else:
            app.logger.debug("Received heartbeat without PID information.")

        return jsonify({'status': 'heartbeat_received'}), 200
    except Exception as e:
        app.logger.error(f"Error processing heartbeat: {e}")
        current_bot_pid = None
        return jsonify({'error': 'Failed to process heartbeat'}), 500

def parse_config():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.py')
    config = {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
                if match:
                    var_name = match.group(1)
                    var_value_str = match.group(2)
                    try:
                        var_value = ast.literal_eval(var_value_str)
                        config[var_name] = var_value
                    except:
                        config[var_name] = var_value_str
        return config
    except FileNotFoundError:
        raise Exception(f"配置文件不存在于: {config_path}")

def update_config(new_values):
    """
    更新配置文件内容，确保文件写入安全性和原子性，避免文件被清空或损坏。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.py')
    lock_path = config_path + '.lock'  # 文件锁路径

    # 使用文件锁，确保只有一个进程/线程能操作 config.py
    with FileLock(lock_path):
        try:
            # 读取现有配置文件内容
            with open(config_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                line_stripped = line.strip()
                # 保留注释或空行
                if line_stripped.startswith('#') or not line_stripped:
                    new_lines.append(line)
                    continue

                # 匹配配置项的键值对
                match = re.match(r'^\s*(\w+)\s*=.*', line)
                if match:
                    var_name = match.group(1)
                    # 如果新配置中包含此变量，更新其值
                    if var_name in new_values:
                        value = new_values[var_name]
                        new_line = f"{var_name} = {repr(value)}\n"
                        new_lines.append(new_line)
                    else:
                        # 保留未修改的变量
                        new_lines.append(line)
                else:
                    # 如果行不符合格式，则直接保留
                    new_lines.append(line)

            # 写入临时文件，确保写入成功后再替换原文件
            with tempfile.NamedTemporaryFile('w', delete=False, dir=script_dir, encoding='utf-8') as temp_file:
                temp_file_name = temp_file.name
                temp_file.writelines(new_lines)

            # 替换原配置文件
            shutil.move(temp_file_name, config_path)
        except Exception as e:
            # 捕获并记录异常，以便排查问题
            raise Exception(f"更新配置文件失败: {e}")

@app.route('/quick_start', methods=['GET', 'POST'])
@login_required
def quick_start():
    if request.method == 'POST':
        try:
            config = parse_config()
            new_values = {}

            api_provider = request.form.get('quick_start_api_provider', 'weapis')
            api_key_raw = request.form.get('quick_start_api_key', '').strip()
            
            # 处理API Key，如果是隐藏版本则保持原值
            if is_hidden_api_key(api_key_raw):
                api_key = config.get('DEEPSEEK_API_KEY', '')
            else:
                api_key = api_key_raw

            keys_to_clear_for_non_weapis = [
                'MOONSHOT_API_KEY', 'ONLINE_API_KEY',
                'MOONSHOT_BASE_URL', 'ONLINE_BASE_URL',
                'MOONSHOT_MODEL', 'ONLINE_MODEL'
            ]

            if api_provider == 'weapis':
                if api_key:
                    new_values['DEEPSEEK_API_KEY'] = api_key
                    new_values['MOONSHOT_API_KEY'] = api_key
                    new_values['ONLINE_API_KEY'] = api_key
                new_values['DEEPSEEK_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['MOONSHOT_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['ONLINE_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['MOONSHOT_MODEL'] = 'gpt-4o'
                new_values['ONLINE_MODEL'] = 'net-gpt-4o-mini'
                if not config.get('MODEL','').strip():
                    new_values['MODEL'] = 'deepseek-ai/DeepSeek-V3'
                new_values['ENABLE_ONLINE_API'] = 'ENABLE_ONLINE_API' in request.form
            
            else:
                if api_provider == 'siliconflow':
                    new_values['DEEPSEEK_BASE_URL'] = 'https://api.siliconflow.cn/v1/'
                elif api_provider == 'deepseek_official':
                    new_values['DEEPSEEK_BASE_URL'] = 'https://api.deepseek.com'
                elif api_provider == 'other':
                    custom_base_url = request.form.get('quick_start_custom_base_url', '').strip()
                    if custom_base_url:
                        new_values['DEEPSEEK_BASE_URL'] = custom_base_url
                    else:
                        new_values['DEEPSEEK_BASE_URL'] = ""
                
                if api_key:
                    new_values['DEEPSEEK_API_KEY'] = api_key
                
                for key_to_clear in keys_to_clear_for_non_weapis:
                    new_values[key_to_clear] = "" 
                new_values['ENABLE_ONLINE_API'] = False

            nicknames = request.form.getlist('nickname')
            prompt_files_form = request.form.getlist('prompt_file')
            new_values['LISTEN_LIST'] = [
                [nick.strip(), pf.strip()]
                for nick, pf in zip(nicknames, prompt_files_form)
                if nick.strip() and pf.strip()
            ]
            new_values['ENABLE_AUTO_MESSAGE'] = 'ENABLE_AUTO_MESSAGE' in request.form
            
            update_config(new_values)
            return redirect(url_for('index'))
        except Exception as e:
            app.logger.error(f"快速配置保存错误: {e}")
            return redirect(url_for('quick_start'))

    try:
        config = parse_config()
        prompt_files_dir = 'prompts'
        if not os.path.exists(prompt_files_dir):
            os.makedirs(prompt_files_dir)
        prompt_files_list = [f[:-3] for f in os.listdir(prompt_files_dir) if f.endswith('.md')]
        
        current_api_provider = 'weapis'
        current_custom_base_url = ''
        
        deepseek_url = config.get('DEEPSEEK_BASE_URL', '')
        
        is_weapis_setup = (
            deepseek_url == 'https://vg.v1api.cc/v1' and
            config.get('MOONSHOT_BASE_URL') == 'https://vg.v1api.cc/v1' and
            config.get('ONLINE_BASE_URL') == 'https://vg.v1api.cc/v1'
        )

        if is_weapis_setup:
            current_api_provider = 'weapis'
        elif deepseek_url == 'https://api.siliconflow.cn/v1/':
            current_api_provider = 'siliconflow'
        elif deepseek_url == 'https://api.deepseek.com':
            current_api_provider = 'deepseek_official'
        elif deepseek_url and deepseek_url != 'https://vg.v1api.cc/v1': 
            current_api_provider = 'other'
            current_custom_base_url = deepseek_url

        # 为快速配置页面也隐藏API Key
        display_config = config.copy()
        api_key_fields = ['DEEPSEEK_API_KEY']
        for field in api_key_fields:
            if field in display_config:
                display_config[field] = hide_api_key(display_config[field])

        return render_template('quick_start.html',
                               config=display_config,
                               prompt_files=prompt_files_list,
                               current_api_provider=current_api_provider,
                               current_custom_base_url=current_custom_base_url)
    except Exception as e:
        app.logger.error(f"加载快速配置页面错误: {e}")
        return "加载快速配置页面错误，请检查日志。"

@app.route('/', methods=['GET'])
@login_required
def index():
    # 在处理 POST 或渲染模板之前检查 API KEY
    current_config_check = parse_config()
    # 检查是否从 quick_start 页面明确跳过
    was_skipped = request.args.get('skipped') == 'true'

    if not current_config_check.get('DEEPSEEK_API_KEY', '').strip():
        # 只有当不是明确跳过，并且是GET请求时，才重定向到 quick_start
        if request.method == 'GET' and not was_skipped:
             return redirect(url_for('quick_start'))

    # GET 请求
    try:
        prompt_files_dir = 'prompts'
        if not os.path.exists(prompt_files_dir):
            os.makedirs(prompt_files_dir)
        prompt_files = [f[:-3] for f in os.listdir(prompt_files_dir) if f.endswith('.md')]
        config = parse_config() # 重新解析以获取最新配置
        chat_context_users = get_chat_context_users()

        # 创建一个隐藏API Key的配置副本用于显示
        display_config = config.copy()
        api_key_fields = ['DEEPSEEK_API_KEY', 'MOONSHOT_API_KEY', 'ONLINE_API_KEY', 'ASSISTANT_API_KEY']
        for field in api_key_fields:
            if field in display_config:
                display_config[field] = hide_api_key(display_config[field])

        return render_template('config_editor.html',
                             config=display_config,
                             prompt_files=prompt_files,
                             chat_context_users=chat_context_users)
    except Exception as e:
        app.logger.error(f"加载主配置页面错误: {e}")
        return "加载配置页面错误，请检查日志。"

# 替换secure_filename的汉字过滤逻辑
def safe_filename(filename):
    # 只保留汉字、字母、数字、下划线和点，其他字符替换为_
    filename = re.sub(r'[^\w\u4e00-\u9fff.]', '_', filename)
    # 防止路径穿越
    filename = filename.replace('../', '_').replace('/', '_')
    return filename

# ===== 知识库面板 =====
def get_knowledge_db_path_from_config():
    config = parse_config()
    db_path = str(config.get('KNOWLEDGE_DB_PATH', 'data/knowledge_base.db') or 'data/knowledge_base.db')
    if not os.path.isabs(db_path):
        db_path = os.path.join(BASE_DIR, db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path

def get_knowledge_upload_dir_from_config():
    config = parse_config()
    upload_dir = str(config.get('KNOWLEDGE_UPLOAD_DIR', 'KnowledgeBaseUploads') or 'KnowledgeBaseUploads')
    if not os.path.isabs(upload_dir):
        upload_dir = os.path.join(BASE_DIR, upload_dir)
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir

def knowledge_db_connect():
    return kb.connect(get_knowledge_db_path_from_config())

def init_knowledge_db_for_editor():
    kb.init_db(get_knowledge_db_path_from_config())

def create_knowledge_document(file_storage, form):
    original_name = file_storage.filename or ''
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in kb.SUPPORTED_EXTENSIONS:
        raise RuntimeError("当前只支持上传 PDF、DOCX、XLSX、TXT、MD。")

    upload_dir = get_knowledge_upload_dir_from_config()
    now_token = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    stored_name = f"{now_token}_{safe_filename(original_name)}"
    stored_path = os.path.join(upload_dir, stored_name)
    file_storage.save(stored_path)

    text = kb.extract_text_from_file(stored_path, ext)
    language_stats = kb.analyze_text_language(text)
    chunks = kb.chunk_text(text)
    if not chunks:
        raise RuntimeError("没有从文件中读取到可用文本；扫描版 PDF 需要后续接入 OCR。")

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = (form.get('title') or os.path.splitext(original_name)[0] or original_name).strip()
    collection = (form.get('collection') or '保险知识').strip()
    trusted_level = (form.get('trusted_level') or '正式资料').strip()
    product_name = (form.get('product_name') or '').strip()
    version = (form.get('version') or '').strip()
    effective_date = (form.get('effective_date') or '').strip()

    init_knowledge_db_for_editor()
    with knowledge_db_connect() as conn:
        cursor = conn.execute("""
            INSERT INTO kb_documents (
                collection, title, source_filename, stored_filename, source_type,
                trusted_level, product_name, version, effective_date,
                enabled, chunk_count, dominant_language, language_summary, language_stats,
                content_char_count, english_word_count, simplified_char_count,
                traditional_char_count, translated_term_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            collection, title, original_name, stored_name, ext.lstrip('.'),
            trusted_level, product_name, version, effective_date,
            len(chunks),
            language_stats.get('dominant_language', ''),
            language_stats.get('language_summary', ''),
            json.dumps(language_stats, ensure_ascii=False),
            language_stats.get('content_char_count', 0),
            language_stats.get('english_word_count', 0),
            language_stats.get('simplified_char_count', 0),
            language_stats.get('traditional_char_count', 0),
            language_stats.get('translated_term_count', 0),
            now_str, now_str
        ))
        document_id = cursor.lastrowid
        for index, chunk in enumerate(chunks):
            conn.execute("""
                INSERT INTO kb_chunks (
                    document_id, chunk_index, title, content, page_number,
                    section_path, enabled, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                document_id, index, title, chunk,
                kb.extract_page_number(chunk), collection, now_str
            ))
        kb.build_index_for_document(conn, document_id)
    return document_id

def list_knowledge_documents():
    return kb.list_documents(get_knowledge_db_path_from_config())

def search_knowledge_documents(query, top_k=8):
    config = parse_config()
    min_score = int(config.get('KNOWLEDGE_MIN_SCORE', 8) or 8)
    return kb.search_knowledge(
        get_knowledge_db_path_from_config(),
        query,
        top_k=top_k,
        min_score=min_score,
    )

@app.route('/knowledge')
@login_required
def knowledge_page():
    config = parse_config()
    docs = list_knowledge_documents()
    index_stats = kb.get_index_stats(get_knowledge_db_path_from_config())
    query = request.args.get('q', '').strip()
    results = search_knowledge_documents(query, top_k=8) if query else []
    return render_template(
        'knowledge_base.html',
        config=config,
        docs=docs,
        index_stats=index_stats,
        query=query,
        results=results
    )

@app.route('/knowledge/rebuild-index', methods=['POST'])
@login_required
def rebuild_knowledge_index():
    try:
        kb.rebuild_all_indexes(get_knowledge_db_path_from_config())
    except Exception as e:
        app.logger.error(f"重建知识库索引失败: {e}", exc_info=True)
        return f"重建知识库索引失败：{e}", 500
    return redirect(url_for('knowledge_page'))

@app.route('/knowledge/upload', methods=['POST'])
@login_required
def upload_knowledge_file():
    file_storage = request.files.get('knowledge_file')
    if not file_storage or not file_storage.filename:
        return redirect(url_for('knowledge_page', error='empty_file'))
    try:
        create_knowledge_document(file_storage, request.form)
    except Exception as e:
        app.logger.error(f"知识库上传失败: {e}", exc_info=True)
        return f"知识库上传失败：{e}", 400
    return redirect(url_for('knowledge_page'))

@app.route('/knowledge/<int:document_id>/toggle', methods=['POST'])
@login_required
def toggle_knowledge_document(document_id):
    init_knowledge_db_for_editor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with knowledge_db_connect() as conn:
        row = conn.execute("SELECT enabled FROM kb_documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            return "知识库文档不存在", 404
        new_enabled = 0 if row['enabled'] else 1
        conn.execute("UPDATE kb_documents SET enabled = ?, updated_at = ? WHERE id = ?", (new_enabled, now_str, document_id))
    return redirect(url_for('knowledge_page'))

@app.route('/knowledge/<int:document_id>/delete', methods=['POST'])
@login_required
def delete_knowledge_document(document_id):
    init_knowledge_db_for_editor()
    stored_filename = None
    with knowledge_db_connect() as conn:
        row = conn.execute("SELECT stored_filename FROM kb_documents WHERE id = ?", (document_id,)).fetchone()
        if row:
            stored_filename = row['stored_filename']
        conn.execute("DELETE FROM kb_documents WHERE id = ?", (document_id,))
    if stored_filename:
        path = os.path.join(get_knowledge_upload_dir_from_config(), safe_filename(stored_filename))
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                app.logger.warning(f"删除知识库原文件失败: {e}")
    return redirect(url_for('knowledge_page'))

# ===== 客户 CRM 面板 =====
def get_customer_db_path_from_config():
    config = parse_config()
    db_path = str(config.get('CUSTOMER_DB_PATH', 'data/customer_assistant.db') or 'data/customer_assistant.db')
    if not os.path.isabs(db_path):
        db_path = os.path.join(BASE_DIR, db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return db_path

def customer_db_connect():
    conn = sqlite3.connect(get_customer_db_path_from_config(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_customer_db_for_editor():
    with customer_db_connect() as conn:
        conn.executescript("""
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wechat_nickname TEXT NOT NULL UNIQUE,
    display_name TEXT,
    birthday TEXT,
    premium_due_date TEXT,
    policy_anniversary TEXT,
    family_status TEXT,
    preferences TEXT,
    personality_style TEXT,
    risk_preference TEXT,
    communication_taboo TEXT,
    sales_stage TEXT DEFAULT '售前-旧客维护',
    current_focus TEXT,
    next_action TEXT,
    reply_strategy TEXT,
    avoid_strategy TEXT,
    needs_handoff INTEGER DEFAULT 0,
    handoff_reason TEXT,
    profile_markdown TEXT,
    last_interaction_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    summary TEXT,
    raw_excerpt TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    due_at TEXT,
    task_type TEXT,
    content TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_customers_wechat_nickname ON customers(wechat_nickname);
CREATE INDEX IF NOT EXISTS idx_customer_events_customer_date ON customer_events(customer_id, event_date);
CREATE INDEX IF NOT EXISTS idx_interactions_customer_created ON interactions(customer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_followups_status_due ON followups(status, due_at);
""")

def row_to_dict(row):
    return dict(row) if row is not None else None

def normalize_date_for_compare(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:len(fmt)], fmt).date()
        except ValueError:
            pass
    if re.match(r"^\d{2}-\d{2}$", text):
        try:
            return datetime.strptime(f"{datetime.now().year}-{text}", "%Y-%m-%d").date()
        except ValueError:
            return None
    return None

def is_date_within_days(value, days):
    target = normalize_date_for_compare(value)
    if not target:
        return False
    today = datetime.now().date()
    if target < today and len(str(value).strip()) == 5:
        try:
            target = target.replace(year=today.year + 1)
        except ValueError:
            return False
    return today <= target <= today + timedelta(days=days)

def customer_matches_view(customer, view):
    if view == 'handoff':
        return bool(customer.get('needs_handoff'))
    if view == 'premium_due':
        return is_date_within_days(customer.get('premium_due_date'), 30)
    if view == 'birthday':
        return is_date_within_days(customer.get('birthday'), 30)
    if view == 'inactive':
        last_dt = normalize_date_for_compare(customer.get('last_interaction_at'))
        if not last_dt:
            return True
        return last_dt <= datetime.now().date() - timedelta(days=30)
    return True

def list_customers_for_crm(view='all', q=''):
    init_customer_db_for_editor()
    q = (q or '').strip()
    with customer_db_connect() as conn:
        rows = conn.execute("""
            SELECT
                id, wechat_nickname, display_name, birthday, premium_due_date,
                policy_anniversary, sales_stage, current_focus, next_action,
                needs_handoff, handoff_reason, last_interaction_at, updated_at
            FROM customers
            ORDER BY
                CASE WHEN needs_handoff THEN 0 ELSE 1 END,
                COALESCE(last_interaction_at, updated_at, created_at) DESC
        """).fetchall()
    customers = [dict(row) for row in rows]
    if q:
        q_lower = q.lower()
        customers = [
            item for item in customers
            if q_lower in str(item.get('wechat_nickname') or '').lower()
            or q_lower in str(item.get('display_name') or '').lower()
            or q_lower in str(item.get('current_focus') or '').lower()
            or q_lower in str(item.get('next_action') or '').lower()
        ]
    return [item for item in customers if customer_matches_view(item, view)]

def get_customer_detail(customer_id):
    init_customer_db_for_editor()
    with customer_db_connect() as conn:
        customer = row_to_dict(conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone())
        if not customer:
            return None
        events = [dict(row) for row in conn.execute(
            "SELECT * FROM customer_events WHERE customer_id = ? ORDER BY COALESCE(event_date, ''), id DESC",
            (customer_id,)
        ).fetchall()]
        interactions = [dict(row) for row in conn.execute(
            "SELECT * FROM interactions WHERE customer_id = ? ORDER BY created_at DESC, id DESC LIMIT 30",
            (customer_id,)
        ).fetchall()]
        followups = [dict(row) for row in conn.execute(
            "SELECT * FROM followups WHERE customer_id = ? ORDER BY CASE WHEN status='done' THEN 1 ELSE 0 END, COALESCE(due_at, ''), id DESC",
            (customer_id,)
        ).fetchall()]
    return {
        'customer': customer,
        'events': events,
        'interactions': interactions,
        'followups': followups,
    }

def build_customer_profile_preview(customer, events=None, followups=None, interactions=None):
    events = events or []
    followups = [item for item in (followups or []) if item.get('status') != 'done']
    interactions = interactions or []
    lines = [
        '## 客户经营档案',
        '',
        f"档案对象：{customer.get('wechat_nickname') or ''}",
        f"档案更新时间：{customer.get('updated_at') or ''}",
        '',
        f"客户阶段：{customer.get('sales_stage') or '售前-旧客维护'}",
        '',
        '关键日期：',
        f"- 生日：{customer.get('birthday') or ''}",
        f"- 保费到期：{customer.get('premium_due_date') or ''}",
        f"- 保单周年：{customer.get('policy_anniversary') or ''}",
    ]
    for event in events:
        note = f"（{event.get('note')}）" if event.get('note') else ''
        lines.append(f"- {event.get('event_type') or '其他'}：{event.get('event_date') or ''}{note}")
    lines.extend([
        '',
        '客户画像：',
        f"- 昵称/姓名：{customer.get('display_name') or ''}",
        f"- 家庭情况：{customer.get('family_status') or ''}",
        f"- 兴趣偏好：{customer.get('preferences') or ''}",
        f"- 性格风格：{customer.get('personality_style') or ''}",
        f"- 风险偏好：{customer.get('risk_preference') or ''}",
        f"- 沟通禁忌：{customer.get('communication_taboo') or ''}",
        '',
        '当前进度：',
        f"- 最近互动时间：{customer.get('last_interaction_at') or ''}",
        f"- 当前关注点：{customer.get('current_focus') or ''}",
        f"- 下一步动作：{customer.get('next_action') or ''}",
        '',
        '回复策略：',
        f"- 应该怎么说：{customer.get('reply_strategy') or ''}",
        f"- 避免怎么说：{customer.get('avoid_strategy') or ''}",
        '',
        '人工接管：',
        f"- 是否需要人工接管：{'是' if customer.get('needs_handoff') else '否'}",
        f"- 原因：{customer.get('handoff_reason') or ''}",
    ])
    if followups:
        lines.extend(['', '未完成跟进：'])
        for item in followups[:10]:
            lines.append(f"- {item.get('due_at') or '未定时间'} | {item.get('task_type') or '跟进'}：{item.get('content') or ''}")
    if interactions:
        lines.extend(['', '最近互动摘要：'])
        for item in interactions[:5]:
            lines.append(f"- {item.get('created_at') or ''}：{item.get('summary') or item.get('raw_excerpt') or ''}")
    return '\n'.join(lines).strip() + '\n'

def sync_customer_memory_cache(customer_id):
    detail = get_customer_detail(customer_id)
    if not detail:
        return
    config = parse_config()
    memory_dir = os.path.join(BASE_DIR, config.get('CUSTOMER_MEMORY_DIR', 'CustomerMemory'))
    os.makedirs(memory_dir, exist_ok=True)
    nickname = safe_filename(detail['customer'].get('wechat_nickname') or f'customer_{customer_id}')
    path = os.path.join(memory_dir, f'{nickname}.md')
    content = build_customer_profile_preview(
        detail['customer'],
        detail['events'],
        detail['followups'],
        detail['interactions']
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

@app.route('/customers')
@login_required
def customers_page():
    view = request.args.get('view', 'all')
    q = request.args.get('q', '')
    customers = list_customers_for_crm(view=view, q=q)
    all_customers = list_customers_for_crm(view='all', q='')
    stats = {
        'all': len(all_customers),
        'handoff': len([c for c in all_customers if customer_matches_view(c, 'handoff')]),
        'premium_due': len([c for c in all_customers if customer_matches_view(c, 'premium_due')]),
        'birthday': len([c for c in all_customers if customer_matches_view(c, 'birthday')]),
        'inactive': len([c for c in all_customers if customer_matches_view(c, 'inactive')]),
    }
    return render_template('customer_crm.html', customers=customers, view=view, q=q, stats=stats)

@app.route('/customers/<int:customer_id>')
@login_required
def customer_detail_page(customer_id):
    detail = get_customer_detail(customer_id)
    if not detail:
        return "客户不存在", 404
    profile_preview = build_customer_profile_preview(
        detail['customer'],
        detail['events'],
        detail['followups'],
        detail['interactions']
    )
    return render_template('customer_detail.html', detail=detail, profile_preview=profile_preview)

@app.route('/customers/<int:customer_id>/update', methods=['POST'])
@login_required
def update_customer_detail(customer_id):
    editable_fields = [
        'display_name', 'birthday', 'premium_due_date', 'policy_anniversary',
        'family_status', 'preferences', 'personality_style', 'risk_preference',
        'communication_taboo', 'sales_stage', 'current_focus', 'next_action',
        'reply_strategy', 'avoid_strategy', 'handoff_reason'
    ]
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    values = {field: request.form.get(field, '').strip() for field in editable_fields}
    needs_handoff = 1 if request.form.get('needs_handoff') == 'on' else 0
    set_sql = ', '.join([f"{field} = ?" for field in editable_fields] + ['needs_handoff = ?', 'updated_at = ?'])
    params = [values[field] for field in editable_fields] + [needs_handoff, now_str, customer_id]
    init_customer_db_for_editor()
    with customer_db_connect() as conn:
        conn.execute(f"UPDATE customers SET {set_sql} WHERE id = ?", params)
    sync_customer_memory_cache(customer_id)
    return redirect(url_for('customer_detail_page', customer_id=customer_id))

@app.route('/customers/<int:customer_id>/followups/add', methods=['POST'])
@login_required
def add_customer_followup(customer_id):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    due_at = request.form.get('due_at', '').strip()
    task_type = request.form.get('task_type', '').strip() or '跟进'
    content = request.form.get('content', '').strip()
    if content:
        init_customer_db_for_editor()
        with customer_db_connect() as conn:
            conn.execute(
                """
                INSERT INTO followups (customer_id, due_at, task_type, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'open', ?, ?)
                """,
                (customer_id, due_at, task_type, content, now_str, now_str)
            )
        sync_customer_memory_cache(customer_id)
    return redirect(url_for('customer_detail_page', customer_id=customer_id))

@app.route('/customers/followups/<int:followup_id>/done', methods=['POST'])
@login_required
def mark_followup_done(followup_id):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    init_customer_db_for_editor()
    with customer_db_connect() as conn:
        row = conn.execute("SELECT customer_id FROM followups WHERE id = ?", (followup_id,)).fetchone()
        if not row:
            return "跟进任务不存在", 404
        customer_id = row['customer_id']
        conn.execute(
            "UPDATE followups SET status = 'done', updated_at = ? WHERE id = ?",
            (now_str, followup_id)
        )
    sync_customer_memory_cache(customer_id)
    return redirect(url_for('customer_detail_page', customer_id=customer_id))

@app.route('/edit_prompt/<filename>', methods=['GET', 'POST'])
@login_required
def edit_prompt(filename):
    safe_dir = os.path.abspath('prompts')
    # 从path中移除.md后缀，如果存在的话，因为safe_filename会处理
    if filename.endswith('.md'):
        filename_no_ext = filename[:-3]
    else:
        filename_no_ext = filename
    
    # 使用 safe_filename 处理，并确保.md后缀
    # 注意：前端JS在调用此接口时，filename参数应该是包含.md的
    # 所以这里的safe_filename应该针对传入的filename
    processed_filename = safe_filename(filename) 
    filepath = os.path.join(safe_dir, processed_filename)

    if request.method == 'POST':
        content = request.form.get('content', '')
        new_filename_from_form = request.form.get('filename', '').strip()

        if not new_filename_from_form.endswith('.md'):
            new_filename_from_form += '.md'
        new_filename_safe = safe_filename(new_filename_from_form)
        new_filepath = os.path.join(safe_dir, new_filename_safe)

        try:
            # 如果文件名改变了
            if new_filename_safe != processed_filename:
                if os.path.exists(new_filepath):
                    return "新文件名已存在", 400 # 返回错误状态码
                # 检查旧文件是否存在
                if not os.path.exists(filepath):
                     return "原文件不存在，无法重命名", 404
                os.rename(filepath, new_filepath)
                filepath = new_filepath # 更新filepath为新路径，以便写入内容
            
            # 写入内容
            with open(filepath, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            # 修改后，不需要重定向到 prompt_list，前端会刷新或处理
            return jsonify({'status': 'success', 'message': 'Prompt已保存'}), 200
        except Exception as e:
            app.logger.error(f"保存Prompt失败: {str(e)}")
            return f"保存失败: {str(e)}", 500

    # GET 请求部分: 返回JSON数据
    try:
        if not os.path.exists(filepath): # 确保文件存在
            return jsonify({'error': '文件不存在'}), 404
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        # 返回JSON，而不是渲染模板
        return jsonify({'filename': processed_filename, 'content': content})
    except FileNotFoundError:
        return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        app.logger.error(f"读取Prompt失败: {str(e)}")
        return jsonify({'error': f'读取Prompt失败: {str(e)}'}), 500

@app.route('/create_prompt', methods=['GET', 'POST'])
@login_required
def create_prompt():
    if request.method == 'POST':
        filename = request.form.get('filename', '').strip()
        content = request.form.get('content', '')
        
        if not filename:
            return "文件名不能为空", 400 # 返回错误状态码
            
        if not filename.endswith('.md'):
            filename += '.md'
        filename = safe_filename(filename) # 应用安全文件名处理
        
        filepath = os.path.join('prompts', filename)
        if os.path.exists(filepath):
            return "文件已存在", 409 # 409 Conflict 更合适
            
        try:
            if not os.path.exists('prompts'): # 确保目录存在
                os.makedirs('prompts')
            with open(filepath, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            # 返回成功JSON，而不是重定向
            return jsonify({'status': 'success', 'message': 'Prompt已创建'}), 201 # 201 Created
        except Exception as e:
            app.logger.error(f"创建Prompt失败: {str(e)}")
            return f"创建失败: {str(e)}", 500
    
    return "此端点用于POST创建Prompt，或GET请求已被整合处理。", 405 # Method Not Allowed for GET

@app.route('/delete_prompt/<filename>', methods=['POST'])
@login_required
def delete_prompt(filename):
    safe_dir = os.path.abspath('prompts')
    filepath = os.path.join(safe_dir, safe_filename(filename))
    
    if os.path.isfile(filepath) and filepath.startswith(safe_dir):
        try:
            os.remove(filepath)
            return '', 204
        except Exception as e:
            return str(e), 500
    return "无效文件", 400

@app.route('/generate_prompt', methods=['POST'])
@login_required
def generate_prompt():
    try:
        # 从config.py获取配置
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL
        
        client = openai.OpenAI(
            base_url=DEEPSEEK_BASE_URL,
            api_key=DEEPSEEK_API_KEY
        )
        
        prompt = request.json.get('prompt', '')
        FixedPrompt = (
            "\n请严格按照以下格式生成提示词（仅参考以下格式，将...替换为合适的内容，不要输出其他多余内容）。"
            "\n注意：仅在<# 输出示例>部分需要输出以'\\'进行分隔的短句，且不输出逗号和句号，其它部分应当正常输出。"
            "\n\n# 任务"
            "\n你需要扮演指定角色，根据角色的经历，模仿她的语气进行线上的日常对话。"
            "\n\n# 角色"
            "\n你将扮演...。"
            "\n\n# 外表"
            "\n...。"
            "\n\n# 经历"
            "\n...。"
            "\n\n# 性格"
            "\n...。"
            "\n# 输出示例"
            "\n...\\...\\..."
            "\n...\\..."
            "\n\n# 喜好"
            "\n...。\n"
        )  # 固定提示词
        
        config = parse_config()
        temperature = config.get('TEMPERATURE', 0.7)

        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{
            "role": "user",
            "content": prompt + FixedPrompt
            }],
            temperature=temperature,
            max_tokens=5000
        )
        
        reply = completion.choices[0].message.content
        if "</think>" in reply:
            reply = reply.split("</think>", 1)[1].strip()

        return jsonify({
            'result': reply
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 获取所有提醒 
@app.route('/get_all_reminders')
@login_required
def get_all_reminders():
    """
    获取 JSON 文件中所有的提醒记录 (包括 recurring 和 one-off)。
    """
    try:
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recurring_reminders.json')
        if not os.path.exists(json_path):
            return jsonify([]) # 文件不存在则返回空列表

        with open(json_path, 'r', encoding='utf-8') as f:
            all_reminders = json.load(f)

        # 基本验证，确保返回的是列表
        if not isinstance(all_reminders, list):
             app.logger.warning(f"文件 {json_path} 内容不是有效的JSON列表，将返回空列表。")
             return jsonify([])

        return jsonify(all_reminders) # <--- 返回所有提醒

    except json.JSONDecodeError:
        app.logger.error(f"文件 recurring_reminders.json 格式错误，无法解析。")
        return jsonify([]) # 格式错误也返回空列表
    except Exception as e:
        app.logger.error(f"获取所有提醒失败: {str(e)}")
        return jsonify({'error': f'获取所有提醒失败: {str(e)}'}), 500


# 重命名: 保存所有提醒 (覆盖整个文件)
@app.route('/save_all_reminders', methods=['POST']) # <--- Route Renamed
@login_required
def save_all_reminders():
    """
    接收前端提交的所有提醒列表 (recurring 和 one-off)，
    验证后覆盖写入 recurring_reminders.json 文件。
    """
    try:
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recurring_reminders.json')
        # 获取前端提交的完整提醒列表
        reminders_data = request.get_json()

        # --- 验证前端提交的数据 ---
        if not isinstance(reminders_data, list):
            raise ValueError("无效的数据格式，应为提醒列表")

        validated_reminders = []
        # 定义验证规则
        recurring_required = ['reminder_type', 'user_id', 'time_str', 'content']
        one_off_required = ['reminder_type', 'user_id', 'target_datetime_str', 'content']
        time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$') # HH:MM
        # YYYY-MM-DD HH:MM (允许个位数月/日，但通常前端datetime-local会补零)
        datetime_pattern = re.compile(r'^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01]) ([01]\d|2[0-3]):([0-5]\d)$')

        for idx, item in enumerate(reminders_data, 1):
            if not isinstance(item, dict):
                 raise ValueError(f"第{idx}条记录不是有效的对象")

            reminder_type = item.get('reminder_type')
            user_id = str(item.get('user_id', '')).strip()
            content = str(item.get('content', '')).strip()

            # 通用验证
            if not reminder_type in ['recurring', 'one-off']:
                 raise ValueError(f"第{idx}条记录类型无效: {reminder_type}")
            if not user_id: raise ValueError(f"第{idx}条用户ID不能为空")
            if len(user_id) > 50: raise ValueError(f"第{idx}条用户ID过长（最大50字符）")
            if not content: raise ValueError(f"第{idx}条内容不能为空")
            if len(content) > 200: raise ValueError(f"第{idx}条内容过长（最大200字符）")

            # 特定类型验证
            if reminder_type == 'recurring':
                if not all(field in item for field in recurring_required):
                    raise ValueError(f"第{idx}条(recurring)记录字段缺失")
                time_str = str(item.get('time_str', '')).strip()
                if not time_pattern.match(time_str):
                    raise ValueError(f"第{idx}条(recurring)时间格式错误，应为 HH:MM ({time_str})")
                validated_reminders.append({
                    'reminder_type': 'recurring',
                    'user_id': user_id,
                    'time_str': time_str,
                    'content': content
                })
            elif reminder_type == 'one-off':
                if not all(field in item for field in one_off_required):
                     raise ValueError(f"第{idx}条(one-off)记录字段缺失")
                target_datetime_str = str(item.get('target_datetime_str', '')).strip()
                # 验证 YYYY-MM-DD HH:MM 格式
                if not datetime_pattern.match(target_datetime_str):
                    raise ValueError(f"第{idx}条(one-off)日期时间格式错误，应为 YYYY-MM-DD HH:MM ({target_datetime_str})")
                validated_reminders.append({
                    'reminder_type': 'one-off',
                    'user_id': user_id,
                    'target_datetime_str': target_datetime_str,
                    'content': content
                })

        # --- 原子化写入操作 ---
        # 使用临时文件确保写入安全，覆盖原文件
        temp_dir = os.path.dirname(json_path)
        with tempfile.NamedTemporaryFile('w', delete=False, dir=temp_dir, encoding='utf-8', suffix='.tmp') as temp_f:
            json.dump(validated_reminders, temp_f, ensure_ascii=False, indent=2) # 写入验证后的完整列表
            temp_path = temp_f.name
        # 替换原文件
        shutil.move(temp_path, json_path)

        return jsonify({'status': 'success', 'message': '所有提醒已更新'})

    except ValueError as ve: # 捕获验证错误
         app.logger.error(f'提醒保存验证失败: {str(ve)}')
         return jsonify({'error': f'数据验证失败: {str(ve)}'}), 400
    except Exception as e:
        app.logger.error(f'提醒保存失败: {str(e)}')
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

@app.route('/import_config', methods=['POST'])
@login_required
def import_config():
    global bot_process
    # 如果 bot 正在运行，则不允许导入配置
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再导入配置'}), 400

    try:
        if 'config_file' not in request.files:
            return jsonify({'error': '未找到上传的配置文件'}), 400
            
        config_file = request.files['config_file']
        if not config_file.filename.endswith('.py'):
            return jsonify({'error': '请上传.py格式的配置文件'}), 400
            
        # 创建临时文件用于解析配置
        with tempfile.NamedTemporaryFile('wb', suffix='.py', delete=False) as temp_f:
            temp_path = temp_f.name
            config_file.save(temp_path)
        
        # 解析临时配置文件
        imported_config = {}
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
                    if match:
                        var_name = match.group(1)
                        var_value_str = match.group(2)
                        try:
                            var_value = ast.literal_eval(var_value_str)
                            imported_config[var_name] = var_value
                        except:
                            imported_config[var_name] = var_value_str
        finally:
            # 清理临时文件
            try:
                os.unlink(temp_path)
            except:
                pass
        
        # 获取当前配置作为基础
        current_config = parse_config()
        
        # 合并配置：只更新导入配置中存在的项
        for key, value in imported_config.items():
            if key in current_config:  # 只更新当前配置中已存在的项
                current_config[key] = value
        
        # 更新配置文件
        update_config(current_config)
        
        return jsonify({'success': True, 'message': '配置导入成功，共导入了{}个有效参数'.format(len(imported_config))}), 200
    except Exception as e:
        app.logger.error(f"配置导入失败: {str(e)}")
        return jsonify({'error': f'导入失败: {str(e)}'}), 500

def create_backup_directory():
    """创建备份目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(BASE_DIR, "数据备份", f"{timestamp}_导入备份")
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def backup_existing_data(backup_dir):
    """备份现有数据到指定目录"""
    backed_up_items = []
    
    try:
        # 备份 prompts 文件夹
        prompts_dir = os.path.join(BASE_DIR, 'prompts')
        if os.path.exists(prompts_dir):
            backup_prompts = os.path.join(backup_dir, 'prompts')
            shutil.copytree(prompts_dir, backup_prompts)
            backed_up_items.append('prompts文件夹')
        
        # 备份 emojis 文件夹
        emojis_dir = os.path.join(BASE_DIR, 'emojis')
        if os.path.exists(emojis_dir):
            backup_emojis = os.path.join(backup_dir, 'emojis')
            shutil.copytree(emojis_dir, backup_emojis)
            backed_up_items.append('emojis文件夹')
        
        # 备份 CoreMemory 文件夹
        config = parse_config()
        core_memory_dir = os.path.join(BASE_DIR, config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        if os.path.exists(core_memory_dir):
            backup_core = os.path.join(backup_dir, os.path.basename(core_memory_dir))
            shutil.copytree(core_memory_dir, backup_core)
            backed_up_items.append('CoreMemory文件夹')
        
        # 备份 recurring_reminders.json 文件
        reminders_file = os.path.join(BASE_DIR, 'recurring_reminders.json')
        if os.path.exists(reminders_file):
            backup_reminders = os.path.join(backup_dir, 'recurring_reminders.json')
            shutil.copy2(reminders_file, backup_reminders)
            backed_up_items.append('recurring_reminders.json文件')
        
        # 备份 chat_contexts.json 文件
        chat_contexts_file = os.path.join(BASE_DIR, 'chat_contexts.json')
        if os.path.exists(chat_contexts_file):
            backup_chat_contexts = os.path.join(backup_dir, 'chat_contexts.json')
            shutil.copy2(chat_contexts_file, backup_chat_contexts)
            backed_up_items.append('chat_contexts.json文件')
        
        # 备份 Memory_Temp 文件夹
        config = parse_config()
        memory_temp_dirname = config.get('MEMORY_TEMP_DIR', 'Memory_Temp')
        memory_temp_dir = os.path.join(BASE_DIR, memory_temp_dirname)
        if os.path.exists(memory_temp_dir):
            backup_memory_temp = os.path.join(backup_dir, memory_temp_dirname)
            shutil.copytree(memory_temp_dir, backup_memory_temp)
            backed_up_items.append('Memory_Temp文件夹')
        
        # 备份 config.py 文件
        config_file = os.path.join(BASE_DIR, 'config.py')
        if os.path.exists(config_file):
            backup_config = os.path.join(backup_dir, 'config.py')
            shutil.copy2(config_file, backup_config)
            backed_up_items.append('config.py文件')
        
        return backed_up_items
    except Exception as e:
        app.logger.error(f"备份数据失败: {str(e)}")
        raise Exception(f"备份失败: {str(e)}")

def import_directory_data(source_dir):
    """从源目录导入数据"""
    imported_items = []
    
    try:
        # 导入 config.py 文件
        source_config = os.path.join(source_dir, 'config.py')
        if os.path.exists(source_config):
            # 解析源配置文件
            imported_config = {}
            with open(source_config, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
                    if match:
                        var_name = match.group(1)
                        var_value_str = match.group(2)
                        try:
                            var_value = ast.literal_eval(var_value_str)
                            imported_config[var_name] = var_value
                        except:
                            imported_config[var_name] = var_value_str
            
            # 获取当前配置并合并
            current_config = parse_config()
            for key, value in imported_config.items():
                if key in current_config:  # 只更新当前配置中已存在的项
                    current_config[key] = value
            
            # 更新配置文件
            update_config(current_config)
            imported_items.append(f'config.py文件（导入了{len(imported_config)}个参数）')
        
        # 导入 prompts 文件夹
        source_prompts = os.path.join(source_dir, 'prompts')
        if os.path.exists(source_prompts):
            target_prompts = os.path.join(BASE_DIR, 'prompts')
            if os.path.exists(target_prompts):
                shutil.rmtree(target_prompts)
            shutil.copytree(source_prompts, target_prompts)
            imported_items.append('prompts文件夹')
        
        # 导入 emojis 文件夹
        source_emojis = os.path.join(source_dir, 'emojis')
        if os.path.exists(source_emojis):
            target_emojis = os.path.join(BASE_DIR, 'emojis')
            if os.path.exists(target_emojis):
                shutil.rmtree(target_emojis)
            shutil.copytree(source_emojis, target_emojis)
            imported_items.append('emojis文件夹')
        
        # 导入 CoreMemory 文件夹
        config = parse_config()
        core_memory_dirname = config.get('CORE_MEMORY_DIR', 'CoreMemory')
        source_core = os.path.join(source_dir, core_memory_dirname)
        if os.path.exists(source_core):
            target_core = os.path.join(BASE_DIR, core_memory_dirname)
            if os.path.exists(target_core):
                shutil.rmtree(target_core)
            shutil.copytree(source_core, target_core)
            imported_items.append('CoreMemory文件夹')
        
        # 导入 recurring_reminders.json 文件
        source_reminders = os.path.join(source_dir, 'recurring_reminders.json')
        if os.path.exists(source_reminders):
            target_reminders = os.path.join(BASE_DIR, 'recurring_reminders.json')
            shutil.copy2(source_reminders, target_reminders)
            imported_items.append('recurring_reminders.json文件')
        
        # 导入 chat_contexts.json 文件
        source_chat_contexts = os.path.join(source_dir, 'chat_contexts.json')
        if os.path.exists(source_chat_contexts):
            target_chat_contexts = os.path.join(BASE_DIR, 'chat_contexts.json')
            shutil.copy2(source_chat_contexts, target_chat_contexts)
            imported_items.append('chat_contexts.json文件')
        
        # 导入 Memory_Temp 文件夹
        config = parse_config()
        memory_temp_dirname = config.get('MEMORY_TEMP_DIR', 'Memory_Temp')
        source_memory_temp = os.path.join(source_dir, memory_temp_dirname)
        if os.path.exists(source_memory_temp):
            target_memory_temp = os.path.join(BASE_DIR, memory_temp_dirname)
            if os.path.exists(target_memory_temp):
                shutil.rmtree(target_memory_temp)
            shutil.copytree(source_memory_temp, target_memory_temp)
            imported_items.append('Memory_Temp文件夹')
        
        return imported_items
    except Exception as e:
        app.logger.error(f"导入目录数据失败: {str(e)}")
        raise Exception(f"导入失败: {str(e)}")

def import_files_data(files_dict):
    """从上传的文件字典导入数据"""
    imported_items = []
    
    try:
        # 创建临时目录来重建文件结构
        temp_dir = tempfile.mkdtemp()
        
        try:
            # 重建文件结构
            for relative_path, file_data in files_dict.items():
                # 标准化路径分隔符
                relative_path = relative_path.replace('\\', '/')
                
                # 处理路径，去除顶级目录（如果有的话）
                path_parts = relative_path.split('/')
                if len(path_parts) > 1:
                    # 如果路径有多级，可能需要去除第一级目录
                    relative_path = '/'.join(path_parts[1:]) if path_parts[0] and path_parts[0] != '.' else relative_path
                
                # 跳过空路径
                if not relative_path:
                    continue
                
                # 创建完整的文件路径
                full_path = os.path.join(temp_dir, relative_path.replace('/', os.sep))
                
                # 确保目录存在
                dir_path = os.path.dirname(full_path)
                if dir_path and dir_path != temp_dir:
                    os.makedirs(dir_path, exist_ok=True)
                
                # 保存文件
                file_data.save(full_path)
                
                app.logger.debug(f"保存文件: {relative_path} -> {full_path}")
            
            # 使用现有的导入函数
            imported_items = import_directory_data(temp_dir)
            
            return imported_items
            
        finally:
            # 清理临时目录
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
                
    except Exception as e:
        app.logger.error(f"导入文件数据失败: {str(e)}")
        raise Exception(f"导入失败: {str(e)}")

@app.route('/import_full_directory', methods=['POST'])
@login_required
def import_full_directory():
    """导入完整的旧版本程序目录"""
    global bot_process
    
    # 如果 bot 正在运行，则不允许导入
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再导入数据'}), 400

    try:
        # 检查是否上传了文件
        if 'directory_files' not in request.files:
            return jsonify({'error': '未找到上传的目录文件'}), 400
            
        uploaded_files = request.files.getlist('directory_files')
        if not uploaded_files:
            return jsonify({'error': '未找到任何文件'}), 400
        
        # 检查是否包含config.py文件
        config_found = False
        files_dict = {}
        
        for file in uploaded_files:
            if file.filename:
                # 获取相对路径（webkitRelativePath）
                relative_path = file.filename
                files_dict[relative_path] = file
                
                # 检查是否有config.py
                if file.filename.endswith('config.py') or file.filename == 'config.py':
                    config_found = True
        
        if not config_found:
            return jsonify({'error': '选择的目录中没有找到config.py文件'}), 400
        
        # 创建备份目录
        backup_dir = create_backup_directory()
        
        # 备份现有数据
        backed_up_items = backup_existing_data(backup_dir)
        
        # 导入新数据
        imported_items = import_files_data(files_dict)
        
        # 构建结果消息
        message = f"完整目录导入成功！\n"
        message += f"共处理了 {len(uploaded_files)} 个文件\n"
        if backed_up_items:
            message += f"已备份的数据: {', '.join(backed_up_items)}\n"
        if imported_items:
            message += f"已导入的数据: {', '.join(imported_items)}\n"
        message += f"备份位置: {backup_dir}"
        
        return jsonify({
            'success': True, 
            'message': message,
            'backed_up_items': backed_up_items,
            'imported_items': imported_items,
            'backup_location': backup_dir,
            'files_count': len(uploaded_files)
        }), 200
                
    except Exception as e:
        app.logger.error(f"完整目录导入失败: {str(e)}")
        return jsonify({'error': f'导入失败: {str(e)}'}), 500

@app.route('/reset_default_config', methods=['POST'])
@login_required
def reset_default_config():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再恢复默认配置'}), 400
    
    try:
        # 获取默认配置
        default_config = get_default_config()
        
        # 保留当前的端口号和登录密码设置（避免被锁在外）
        current_config = parse_config()
        if 'PORT' in current_config:
            default_config['PORT'] = current_config['PORT']
        if 'LOGIN_PASSWORD' in current_config:
            default_config['LOGIN_PASSWORD'] = current_config['LOGIN_PASSWORD']
        if 'ENABLE_LOGIN_PASSWORD' in current_config:
            default_config['ENABLE_LOGIN_PASSWORD'] = current_config['ENABLE_LOGIN_PASSWORD']
        
        # 使用 update_config 函数来保留原有的注释和格式
        update_config(default_config)
        
        app.logger.info("配置已恢复到默认值")
        return jsonify({'message': '配置已恢复到默认值'}), 200
        
    except Exception as e:
        app.logger.error(f"恢复默认配置失败: {e}")
        return jsonify({'error': f'恢复默认配置失败: {str(e)}'}), 500

class WebLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        log_queue.put(log_entry)

# 配置日志处理器
web_handler = WebLogHandler()
web_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(web_handler)

@app.route('/stream')
@login_required
def stream():
    def event_stream():
        retry_count = 0
        while True:
            try:
                log = log_queue.get(timeout=5)
                yield f"data: {log}\n\n"
                retry_count = 0  # 成功时重置重试计数器
            except Empty:
                yield ":keep-alive\n\n"  # 发送心跳包
                retry_count = min(retry_count + 1, 5)
                time.sleep(2 ** retry_count)  # 指数退避
            except Exception as e:
                app.logger.error(f"SSE Error: {str(e)}")
                yield "event: error\ndata: Connection closed\n\n"
                break
    
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route('/api/log', methods=['POST'])
def receive_bot_log():
    try:
        # 增加Content-Type检查
        if not request.is_json:
            return jsonify({'error': 'Unsupported Media Type'}), 415

        # 支持两种格式：单个日志或日志数组
        if 'logs' in request.json:  # 批量日志
            logs_data = request.json.get('logs', [])
            if isinstance(logs_data, list):
                for log_entry in logs_data:
                    if log_entry:
                        # 添加进程标识和颜色标记
                        colored_log = f"[BOT] \033[34m{log_entry.strip()}\033[0m"
                        log_queue.put(colored_log)
                return jsonify({'status': 'success', 'processed': len(logs_data)})
            return jsonify({'error': 'Invalid logs format'}), 400
            
        elif 'log' in request.json:  # 兼容单条日志格式
            log_data = request.json.get('log')
            if log_data:
                # 添加进程标识和颜色标记
                colored_log = f"[BOT] \033[34m{log_data.strip()}\033[0m"
                log_queue.put(colored_log)
            return jsonify({'status': 'success'})
            
        else:
            return jsonify({'error': 'Missing log data'}), 400
            
    except Exception as e:
        app.logger.error(f"日志接收失败: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_chat_context_users', methods=['GET'])
@login_required
def api_get_chat_context_users():
    users = get_chat_context_users()
    return jsonify({'users': users})

@app.route('/clear_chat_context/<username>', methods=['POST'])
@login_required
def clear_chat_context(username):
    """清除指定用户的聊天上下文"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return jsonify({'status': 'error', 'message': '聊天上下文文件不存在'}), 404

    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            with open(CHAT_CONTEXTS_FILE, 'r+', encoding='utf-8') as f:
                data = json.load(f)
                if username in data:
                    del data[username]
                    f.seek(0) # 回到文件开头
                    json.dump(data, f, ensure_ascii=False, indent=4)
                    f.truncate() # 删除剩余内容
                    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的聊天上下文已清除"})
                else:
                    return jsonify({'status': 'error', 'message': f"用户 '{username}' 未找到"}), 404
        except (json.JSONDecodeError, IOError) as e:
            app.logger.error(f"处理 chat_contexts.json 失败: {e}")
            return jsonify({'status': 'error', 'message': '处理聊天上下文文件失败'}), 500

# 聊天上下文编辑API
@app.route('/api/get_chat_context/<username>', methods=['GET'])
@login_required
def get_user_chat_context(username):
    """获取指定用户的聊天上下文"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return jsonify({'error': '聊天上下文文件未找到'}), 404

    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                contexts = json.load(f)
            user_context = contexts.get(username)
            if user_context is None:
                return jsonify({'error': f"用户 '{username}' 在上下文中不存在"}), 404
            pretty_context = json.dumps(user_context, ensure_ascii=False, indent=4)
            return jsonify({'status': 'success', 'context': pretty_context})
        except (json.JSONDecodeError, IOError) as e:
            app.logger.error(f"读取或解析聊天上下文文件失败: {e}")
            return jsonify({'error': f'读取或解析文件失败: {e}'}), 500

@app.route('/api/save_chat_context/<username>', methods=['POST'])
@login_required
def save_user_chat_context(username):
    """保存指定用户修改后的聊天上下文，强制合并连续user消息，确保user→assistant结构"""
    if bot_process and bot_process.poll() is not None:
        return jsonify({'error': '程序正在运行，请先停止再保存上下文'}), 400
    data = request.get_json()
    if not data or 'context' not in data:
        return jsonify({'status': 'error', 'message': '请求无效，缺少 "context" 字段'}), 400
    new_context_str = data['context']
    try:
        new_context_data = json.loads(new_context_str)
        if not isinstance(new_context_data, list):
            raise ValueError("上下文数据必须是一个JSON数组 (list)")
        # --- 强制合并连续user，保证user→assistant结构 ---
        merged_context = []
        user_buffer = []
        for item in new_context_data:
            if item.get('role') == 'user':
                user_buffer.append(item.get('content', ''))
            elif item.get('role') == 'assistant':
                if user_buffer:
                    merged_context.append({'role': 'user', 'content': '\n'.join(user_buffer)})
                    user_buffer = []
                merged_context.append(item)
        if user_buffer:
            merged_context.append({'role': 'user', 'content': '\n'.join(user_buffer)})
        # --- END ---
    except (json.JSONDecodeError, ValueError) as e:
        return jsonify({'status': 'error', 'message': f'格式错误: {str(e)}'}), 400
    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            if not os.path.exists(CHAT_CONTEXTS_FILE):
                return jsonify({'status': 'error', 'message': '聊天上下文文件未找到'}), 404
            with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                all_contexts = json.load(f)
            if username not in all_contexts:
                return jsonify({'status': 'error', 'message': '用户在上下文中不存在'}), 404
            all_contexts[username] = merged_context
            temp_file_path = CHAT_CONTEXTS_FILE + ".tmp"
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(all_contexts, f, ensure_ascii=False, indent=4)
            shutil.move(temp_file_path, CHAT_CONTEXTS_FILE)
        except Exception as e:
            app.logger.error(f"保存聊天上下文失败: {e}")
            return jsonify({'status': 'error', 'message': f'保存失败: {str(e)}'}), 500
    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的上下文已更新"})

@app.route('/api/get_core_memory_files', methods=['GET'])
@login_required
def get_core_memory_files():
    """获取核心记忆文件列表"""
    try:
        # 从配置中获取核心记忆目录
        config = parse_config()
        core_memory_dir = os.path.join(os.path.dirname(__file__), config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        
        # 确保目录存在
        os.makedirs(core_memory_dir, exist_ok=True)
        
        files = []
        if os.path.exists(core_memory_dir):
            for filename in os.listdir(core_memory_dir):
                if filename.endswith('_core_memory.json'):
                    file_path = os.path.join(core_memory_dir, filename)
                    try:
                        # 读取文件获取记忆片段数量
                        with open(file_path, 'r', encoding='utf-8') as f:
                            memories = json.load(f)
                        
                        memory_count = len(memories) if isinstance(memories, list) else 0
                        
                        # 获取文件修改时间
                        mtime = os.path.getmtime(file_path)
                        last_modified = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                        
                        # 从文件名提取显示名称
                        display_name = filename.replace('_core_memory.json', '').replace('_', ' - ')
                        
                        files.append({
                            'filename': filename,
                            'display_name': display_name,
                            'memory_count': memory_count,
                            'last_modified': last_modified
                        })
                    except Exception as e:
                        app.logger.warning(f"读取核心记忆文件 {filename} 失败: {e}")
                        continue
        
        # 按修改时间倒序排列
        files.sort(key=lambda x: x['last_modified'], reverse=True)
        
        return jsonify({'status': 'success', 'files': files})
        
    except Exception as e:
        app.logger.error(f"获取核心记忆文件列表失败: {e}")
        return jsonify({'status': 'error', 'message': f'获取失败: {str(e)}'}), 500

@app.route('/api/get_core_memory/<filename>', methods=['GET'])
@login_required  
def get_core_memory(filename):
    """获取指定核心记忆文件的内容"""
    try:
        # 验证文件名安全性
        if not filename.endswith('_core_memory.json'):
            return jsonify({'status': 'error', 'error': '无效的文件名'}), 400
            
        config = parse_config()
        core_memory_dir = os.path.join(os.path.dirname(__file__), config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        file_path = os.path.join(core_memory_dir, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'status': 'error', 'error': '文件不存在'}), 404
        
        # 读取记忆文件
        with open(file_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
        
        # 确保返回的是列表格式
        if not isinstance(memories, list):
            memories = []
        
        # 字段名兼容性处理：处理旧版本的time字段，统一使用timestamp字段
        for memory in memories:
            if isinstance(memory, dict):
                # 如果有旧版本的time字段但没有timestamp字段，则将time转换为timestamp
                if 'time' in memory and 'timestamp' not in memory:
                    memory['timestamp'] = memory['time']
                    del memory['time']  # 删除旧字段，避免冗余
            
        return jsonify({'status': 'success', 'memories': memories})
        
    except Exception as e:
        app.logger.error(f"获取核心记忆文件 {filename} 失败: {e}")
        return jsonify({'status': 'error', 'error': f'读取失败: {str(e)}'}), 500

@app.route('/api/save_core_memory/<filename>', methods=['POST'])
@login_required
def save_core_memory(filename):
    """保存核心记忆到指定文件"""
    try:
        # 验证文件名安全性
        if not filename.endswith('_core_memory.json'):
            return jsonify({'status': 'error', 'message': '无效的文件名'}), 400
            
        data = request.json
        memories = data.get('memories', [])
        
        # 验证数据格式
        if not isinstance(memories, list):
            return jsonify({'status': 'error', 'message': '记忆数据必须是数组格式'}), 400
        
        # 验证每个记忆片段的格式
        for i, memory in enumerate(memories):
            if not isinstance(memory, dict):
                return jsonify({'status': 'error', 'message': f'第{i+1}个记忆片段格式错误'}), 400
            
            # 字段名兼容性检查：支持time字段，但统一转换为timestamp
            if 'time' in memory and 'timestamp' not in memory:
                memory['timestamp'] = memory['time']
                del memory['time']  # 删除旧字段，避免冗余
            
            # 验证必要字段
            if 'timestamp' not in memory or 'importance' not in memory or 'summary' not in memory:
                return jsonify({'status': 'error', 'message': f'第{i+1}个记忆片段缺少必要字段(timestamp、importance、summary)'}), 400
                
            if not isinstance(memory['importance'], int) or not (1 <= memory['importance'] <= 10):
                return jsonify({'status': 'error', 'message': f'第{i+1}个记忆片段的重要度必须是1-10的整数'}), 400
        
        config = parse_config()
        core_memory_dir = os.path.join(os.path.dirname(__file__), config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        os.makedirs(core_memory_dir, exist_ok=True)
        
        file_path = os.path.join(core_memory_dir, filename)
        
        # 保存记忆文件
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        
        app.logger.info(f"已保存核心记忆文件: {filename}")
        return jsonify({'status': 'success', 'message': '核心记忆已保存'})
        
    except Exception as e:
        app.logger.error(f"保存核心记忆文件 {filename} 失败: {e}")
        return jsonify({'status': 'error', 'message': f'保存失败: {str(e)}'}), 500

@app.route('/api/delete_core_memory/<filename>', methods=['DELETE'])
@login_required
def delete_core_memory(filename):
    """删除核心记忆文件"""
    try:
        # 验证文件名安全性
        if not filename.endswith('_core_memory.json'):
            return jsonify({'status': 'error', 'message': '无效的文件名'}), 400
            
        config = parse_config()
        core_memory_dir = os.path.join(os.path.dirname(__file__), config.get('CORE_MEMORY_DIR', 'CoreMemory'))
        file_path = os.path.join(core_memory_dir, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'status': 'error', 'message': '文件不存在'}), 404
        
        # 删除文件
        os.remove(file_path)
        
        app.logger.info(f"已删除核心记忆文件: {filename}")
        return jsonify({'status': 'success', 'message': '核心记忆文件已删除'})
        
    except Exception as e:
        app.logger.error(f"删除核心记忆文件 {filename} 失败: {e}")
        return jsonify({'status': 'error', 'message': f'删除失败: {str(e)}'}), 500

def run_bat_file():
    bat_file_path = "一键检测.bat"
    if os.path.exists(bat_file_path):
        os.system(f"start {bat_file_path}")

from multiprocessing import Process
import random
from datetime import datetime, timedelta
@app.route('/run_one_key_detection', methods=['GET'])
def run_one_key_detection():
    bat_file_path = "一键检测.bat"
    if os.path.exists(bat_file_path):
        # 使用独立的进程运行 .bat 文件
        p = Process(target=run_bat_file)
        p.start()
        return """
        <h2>启动成功！</h2>
        <p>一键检测工具已成功启动！</p>
        <ul>
            <li>检测工具将在单独的端口上运行，并自动打开浏览器窗口显示检测结果。</li>
            <li>启动后，检测工具将在3分钟后自动关闭进程。</li>
        </ul>
        <h3>检测功能：</h3>
        <ul>
            <li>微信环境检测：检查微信版本、登录状态和窗口状态。</li>
            <li>API配置检测：验证API密钥和连接状态。</li>
            <li>系统资源检测：分析CPU、内存使用情况。</li>
            <li>生成详细的诊断报告：提供问题解决建议。</li>
        </ul>
        <p style="color: green; font-weight: bold;">提示：本页面可以安全关闭，检测工具将在后台运行。</p>
        """
    return """
    <h2>启动失败</h2>
    <p style="color: red;">未找到一键检测.bat，请检查路径是否正确。</p>
    <p>请确保<b>一键检测.bat</b>文件位于程序当前运行目录下。</p>
    """

def get_default_config():
    return {
        "LISTEN_LIST": [['微信名1', '角色1']],
        "DEEPSEEK_API_KEY": '',
        "DEEPSEEK_BASE_URL": 'https://vg.v1api.cc/v1',
        "MODEL": 'deepseek-v3-0324',
        "MAX_GROUPS": 5,
        "MAX_TOKEN": 2000,
        "TEMPERATURE": 1.1,
        "MOONSHOT_API_KEY": '',
        "MOONSHOT_BASE_URL": 'https://vg.v1api.cc/v1',
        "MOONSHOT_MODEL": 'gpt-4o',
        "MOONSHOT_TEMPERATURE": 0.8,
        "ENABLE_IMAGE_RECOGNITION": True,
        "ENABLE_EMOJI_RECOGNITION": True,
        "QUEUE_WAITING_TIME": 7,
        "EMOJI_DIR": 'emojis',
        "ENABLE_EMOJI_SENDING": True,
        "EMOJI_SENDING_PROBABILITY": 25,
        "AUTO_MESSAGE": '请你模拟系统设置的角色，在微信上找对方继续刚刚的话题或者询问对方在做什么',
        "ENABLE_AUTO_MESSAGE": True,
        "MIN_COUNTDOWN_HOURS": 1.0,
        "MAX_COUNTDOWN_HOURS": 2.0,
        "QUIET_TIME_START": '22:00',
        "QUIET_TIME_END": '8:00',
        "AVERAGE_TYPING_SPEED": 0.2,
        "RANDOM_TYPING_SPEED_MIN": 0.05,
        "RANDOM_TYPING_SPEED_MAX": 0.1,
        "SEPARATE_ROW_SYMBOLS": True,
        "ENABLE_REPLY_LENGTH_LIMIT": True,
        "REPLY_MAX_SEGMENTS": 3,
        "REPLY_MAX_TOTAL_CHARS": 30,
        "ENABLE_MEMORY": True,
        "MEMORY_TEMP_DIR": 'Memory_Temp',
        "MAX_MESSAGE_LOG_ENTRIES": 30,
        "MAX_MEMORY_NUMBER": 50,
        "UPLOAD_MEMORY_TO_AI": True,
        "ACCEPT_ALL_GROUP_CHAT_MESSAGES": False,
        "ENABLE_GROUP_AT_REPLY": True,
        "ENABLE_GROUP_KEYWORD_REPLY": False,
        "GROUP_KEYWORD_LIST": ['你好', '机器人', '在吗'],
        "GROUP_CHAT_RESPONSE_PROBABILITY": 100,
        "GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY": True,
        "ENABLE_LOGIN_PASSWORD": False,
        "LOGIN_PASSWORD": '',
        "PORT": 5000,
        "ENABLE_REMINDERS": True,
        "ALLOW_REMINDERS_IN_QUIET_TIME": True,
        "USE_VOICE_CALL_FOR_REMINDERS": False,
        "ENABLE_ONLINE_API": False,
        "ONLINE_BASE_URL": 'https://vg.v1api.cc/v1',
        "ONLINE_MODEL": 'net-gpt-4o-mini',
        "ONLINE_API_KEY": '',
        "ONLINE_API_TEMPERATURE": 0.7,
        "ONLINE_API_MAX_TOKEN": 2000,
        "SEARCH_DETECTION_PROMPT": '是否需要查询今天的天气、最新的新闻事件、特定网站的内容、股票价格、特定人物的最新动态等',
        "ONLINE_FIXED_PROMPT": '',
        "ENABLE_URL_FETCHING": True,
        "REQUESTS_TIMEOUT": 10,
        "REQUESTS_USER_AGENT": 'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36',
        "MAX_WEB_CONTENT_LENGTH": 2000,
        "ENABLE_SCHEDULED_RESTART": True,
        "RESTART_INTERVAL_HOURS": 2.0,
        "RESTART_INACTIVITY_MINUTES": 15,
        "REMOVE_PARENTHESES": False,
        "ENABLE_ASSISTANT_MODEL": False,
        "ASSISTANT_BASE_URL": 'https://vg.v1api.cc/v1',
        "ASSISTANT_MODEL": 'gpt-4o-mini',
        "ASSISTANT_API_KEY": '',
        "ASSISTANT_TEMPERATURE": 0.3,
        "ASSISTANT_MAX_TOKEN": 1000,
        "USE_ASSISTANT_FOR_MEMORY_SUMMARY": False,
        "IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE": False,
        "ENABLE_SENSITIVE_CONTENT_CLEARING": True,
        "SAVE_MEMORY_TO_SEPARATE_FILE": True,
        "CORE_MEMORY_DIR": 'CoreMemory',
        "ENABLE_CUSTOMER_MEMORY": True,
        "ENABLE_CUSTOMER_DB": True,
        "CUSTOMER_DB_PATH": 'data/customer_assistant.db',
        "CUSTOMER_MEMORY_DIR": 'CustomerMemory',
        "CUSTOMER_MEMORY_PRIVATE_ONLY": True,
        "CUSTOMER_MEMORY_AUTO_UPDATE": True,
        "CUSTOMER_MEMORY_MAX_CHARS": 3000,
        "ENABLE_KNOWLEDGE_BASE": True,
        "KNOWLEDGE_DB_PATH": 'data/knowledge_base.db',
        "KNOWLEDGE_UPLOAD_DIR": 'KnowledgeBaseUploads',
        "KNOWLEDGE_AUTO_SEARCH": True,
        "KNOWLEDGE_TOP_K": 5,
        "KNOWLEDGE_MAX_CONTEXT_CHARS": 2500,
        "KNOWLEDGE_MIN_SCORE": 8,
        "ENABLE_TEXT_COMMANDS": True,
    }

def validate_config():
    """验证config.py配置完整性，若有缺失项则自动补充默认值"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.py')
    
    try:
        # 如果配置文件不存在，直接创建完整配置
        if not os.path.exists(config_path):
            print(f"配置文件不存在，正在创建新配置文件: {config_path}")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write("# -*- coding: utf-8 -*-\n\n")
                f.write("# 自动生成的配置文件\n\n")
                
                for key, value in get_default_config().items():
                    f.write(f"{key} = {repr(value)}\n")
            print("已创建新的配置文件")
            return True
        
        # 尝试解析当前配置
        current_config = parse_config()
        default_config = get_default_config()
        
        # 记录缺少的配置项
        missing_keys = []
        # 构建需要更新的配置字典
        updates_needed = {}
        
        # 检查每个默认配置项是否存在
        for key, default_value in default_config.items():
            if key not in current_config:
                missing_keys.append(key)
                updates_needed[key] = default_value
        
        # 如果存在缺失项，更新配置文件
        if missing_keys:
            print(f"检测到{len(missing_keys)}个缺失的配置项: {', '.join(missing_keys)}")
            print("正在自动补充默认值...")
            
            # 直接修改文件，添加缺失的配置项
            with open(config_path, 'a', encoding='utf-8') as f:
                f.write("\n# 自动补充的配置项\n")
                for key in missing_keys:
                    f.write(f"{key} = {repr(default_config[key])}\n")
            
            print("配置文件已更新完成")
            return True  # 配置已更新
        
        print("配置文件验证完成，所有配置项齐全")
        return False  # 配置无需更新
        
    except Exception as e:
        print(f"验证配置文件时出错: {str(e)}")
        return False
def kill_process_using_port(port):
    """
    检查指定端口是否被占用，如果被占用则结束占用的进程
    """
    # 遍历所有连接
    for conn in psutil.net_connections():
        # 由于 config 中 PORT 可能为字符串，转换为 int
        if conn.laddr and conn.laddr.port == port:
            # 根据不同平台，监听状态可能不同（Linux一般为 'LISTEN'，Windows为 'LISTENING'）
            if conn.status in ('LISTEN', 'LISTENING'):
                try:
                    proc = psutil.Process(conn.pid)
                    print(f"检测到端口 {port} 被进程 {conn.pid} 占用，尝试结束该进程……")
                    proc.kill()
                    proc.wait(timeout=3)
                    print(f"进程 {conn.pid} 已被成功结束。")
                except Exception as e:
                    print(f"结束进程 {conn.pid} 时出现异常：{e}")

if __name__ == '__main__':
    # 配置应用日志级别
    app.logger.setLevel(logging.INFO)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    app.logger.addHandler(console_handler)
    
    class BotStatusFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            # 如果日志消息中包含以下日志，则返回 False（不记录）
            if '/bot_status' in msg or \
               '/api/log' in msg or \
               '/save_all_reminders' in msg or \
               '/get_all_reminders' in msg or \
               '/api/get_chat_context_users' in msg or \
               '/bot_heartbeat' in msg:
                return False
            return True

    # 获取 werkzeug 的日志记录器并添加过滤器
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.addFilter(BotStatusFilter())

    # 验证配置文件完整性
    validate_config()

    # 配置文件存在检查
    config_path = os.path.join(os.path.dirname(__file__), 'config.py')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"核心配置文件缺失: {config_path}")
    
    config = parse_config()
    PORT = config.get('PORT', '5000')

    # 在启动服务器前检查端口是否被占用，若占用则结束该进程
    kill_process_using_port(PORT)

    print("\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print("\033[32m✅ 配置编辑器启动成功！\033[0m")
    print("\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print("")
    print(f"\033[36m📡 访问地址: http://localhost:{config.get('PORT', '5000')}/\033[0m")
    print("\033[90m   → 浏览器将自动打开，如未打开请手动访问上述地址\033[0m")
    if config.get('ENABLE_LOGIN_PASSWORD', False):
        print("")
        print(f"\033[33m🔐 登录密码: {config.get('LOGIN_PASSWORD', '未设置')}\033[0m")
        print("\033[90m   → 请妥善保管，勿泄露给他人\033[0m")
    print("")
    print("\033[33m💡 常见问题：\033[0m")
    print("\033[90m   问题1: 点击Start Bot没反应，提示微信窗口找不到\033[0m")
    print("\033[90m        → 解决: 重启一次微信\033[0m")
    print("")
    print("\033[90m   问题2: 导入配置后出现404心跳报错日志\033[0m")
    print("\033[90m        → 解决: 重启一次Run.bat\033[0m")
    print("")
    print("\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    
    # 在启动服务器前设置定时器打开浏览器
    def open_browser():
        webbrowser.open(f'http://localhost:{PORT}/')
    
    Timer(1, open_browser).start()  # 延迟1秒确保服务器已启动
    
    # 根据配置决定绑定地址
    #host = "0.0.0.0" if config.get('ENABLE_LOGIN_PASSWORD', False) else "127.0.0.1"
    app.run(host= "127.0.0.1", debug=False, port=PORT)
    
