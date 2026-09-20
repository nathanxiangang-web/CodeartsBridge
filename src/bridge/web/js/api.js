const API = {
  async get(path) {
    const resp = await fetch('/api/' + path);
    return resp.json();
  },
  async delete(path) {
    const resp = await fetch('/api/' + path, { method: 'DELETE' });
    return { status: resp.status, data: await resp.json() };
  },
  health() { return this.get('health'); },
  tasks() { return this.get('tasks'); },
  task(id) { return this.get('tasks/' + id); },
  taskLog(id) { return this.get('tasks/' + id + '/log'); },
  workers() { return this.get('workers'); },
  projects() { return this.get('projects'); },
  deleteTask(id) { return this.delete('tasks/' + id); },
};
