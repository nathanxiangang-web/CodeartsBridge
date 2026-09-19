const API = {
  async get(path) {
    const resp = await fetch('/api/' + path);
    return resp.json();
  },
  health() { return this.get('health'); },
  tasks() { return this.get('tasks'); },
  task(id) { return this.get('tasks/' + id); },
  taskLog(id) { return this.get('tasks/' + id + '/log'); },
  workers() { return this.get('workers'); },
  projects() { return this.get('projects'); },
};
