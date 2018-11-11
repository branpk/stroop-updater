import urllib.request
import json
import sys
import os
import re
import shutil
import threading
import tempfile
import zipfile
import time
import traceback
import glob
import functools
import subprocess

import dateutil.parser

os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))


@functools.total_ordering
class Version:

  def __init__(self, dev, version_number):
    self.dev = dev
    self.version_number = version_number

  def parse(version_str):
    if version_str.startswith('dev-'):
      version_str = version_str[len('dev-'):]
      dev = True
    else:
      dev = False
    version_str = version_str[len('v'):]
    return Version(dev, version_str.split('.'))

  def __str__(self):
    return ('dev-' if self.dev else '') + 'v' + '.'.join(map(str, self.version_number))

  def __eq__(self, other):
    return self.dev == other.dev and self.version_number == other.version_number

  def __lt__(self, other):
    if self.dev != other.dev:
      raise ValueError('Comparing dev and release versions')
    return self.version_number < other.version_number


class Install:

  def begin(config, version, download_url, install_path):
    install = Install()
    install.install_id = config['next_install_id']
    config['next_install_id'] += 1

    def report(count, block_size, total_size):
      if total_size != 0:
        install.progress = min(count * block_size, total_size) / total_size

    def thread():
      try:
        with tempfile.TemporaryDirectory() as temp_dir:
          install.action = 'Downloading'
          urllib.request.urlretrieve(download_url, temp_dir + '/STROOP.zip', reporthook=report)

          install.progress = None
          install.action = 'Extracting'
          with zipfile.ZipFile(temp_dir + '/STROOP.zip', 'r') as zip_file:
            zip_file.extractall(temp_dir + '/contents')

          install.action = 'Installing'
          shutil.move(temp_dir + '/contents', install_path)

          config['installed'].append({
              'install_id': install.install_id,
              'version': str(version),
              'path': install_path,
            })

          install.action = 'Done'
      except:
        install.action = 'Failed'
        install.error_msg = traceback.format_exc()

    install.thread = threading.Thread(target=thread)
    install.action = 'Queued'
    install.progress = None

    install.thread.start()
    return install

  def is_done(self):
    return not self.thread.is_alive()

  def failed(self):
    return self.action == 'Failed'


def load_config():
  if os.path.isfile('config.json'):
    with open('config.json', 'r') as f:
      config = json.loads(f.read())
  else:
    config = {'config_version': 0}

  if config['config_version'] == 0:
    config['config_version'] = 1
    config['default_install_id'] = None
    config['installed'] = []
    config['next_install_id'] = 1

  assert config['config_version'] == 1
  return config


def save_config(config):
  config = json.dumps(config, indent=2)
  with open('config.json', 'w') as f:
    f.write(config)


def get_version_from_release(release):
  tag_name = release['tag_name']
  if tag_name[0] == 'v':
    tag_name = tag_name[1:]

  if tag_name == 'Dev':
    dev = True
    version_number = re.search('v[\d\.]+(\s|$)', release['body']).group(0)[1:].split('.')
  else:
    dev = False
    version_number = tuple(map(int, tag_name.split('.')))
  return Version(dev, version_number)


def get_default_install_path(config, version):
  base_path = 'versions/' + str(version)
  path = base_path

  suffix = 0
  while os.path.exists(path):
    suffix += 1
    path = base_path + '-' + str(suffix)

  return path


def uninstall_version(config, install_id):
  try:
    install = [i for i in config['installed'] if i['install_id'] == install_id][0]
    print('Uninstalling version ' + install['version'])

    # Attempt to delete .exe first in case the program is running
    exe = glob.glob(install['path'] + '/**/STROOP.exe', recursive=True)[0]
    os.remove(exe)

    config['installed'].remove(install)
    if config['default_install_id'] == install_id:
      config['default_install_id'] = None
    save_config(config)

    shutil.rmtree(install['path'])
  except:
    print('Uninstallation failed')
    print(traceback.format_exc())


def launch_app(config, install_id):
  launch_install = [i for i in config['installed'] if i['install_id'] == install_id][0]
  launch_exe = glob.glob(launch_install['path'] + '/**/STROOP.exe', recursive=True)[0]

  print('Launching ' + launch_install['version'] + ' (' + launch_exe + ')')
  subprocess.Popen(launch_exe, cwd=os.path.dirname(launch_exe))


config = load_config()
installed_versions = [Version.parse(i['version']) for i in config['installed']]

latest_installed_dev = max([v for v in installed_versions if v.dev], default=None)
latest_installed_release = max([v for v in installed_versions if not v.dev], default=None)


if config['default_install_id'] is None:
  print('Performing first time install. You\'ll need to run the launcher again after it completes.')
else:
  launch_app(config, config['default_install_id'])


print('Checking for updates')
try:
  with urllib.request.urlopen('https://api.github.com/repos/SM64-TAS-ABC/STROOP/releases') as response:
    releases = json.loads(response.read().decode('utf-8'))

  for release in releases:
    version = get_version_from_release(release)
    timestamp = dateutil.parser.parse(release['assets'][0]['updated_at'])

    if version.dev and latest_installed_dev is not None and version <= latest_installed_dev:
      continue
    if not version.dev and latest_installed_release is not None and version <= latest_installed_release:
      continue

    if not version.dev: continue

    download_url = release['assets'][0]['browser_download_url']
    install_path = get_default_install_path(config, version)

    print('Installing ' + str(version))
    install = Install.begin(config, version, download_url, install_path)
    while not install.is_done():
      print(install.action, install.progress or '')
      time.sleep(1)
    if install.failed():
      print('Failed to install version ' + str(version))
      print(install.error_msg)
    else:
      config['default_install_id'] = install.install_id

    save_config(config)

except:
  print('Failed to check for new STROOP versions')
  print(traceback.format_exc())


print('Uninstalling old versions')
for install in list(config['installed']):
  if config['default_install_id'] != install['install_id']:
    uninstall_version(config, install['install_id'])
