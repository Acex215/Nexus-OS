import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.DEV ? '' : `http://${window.location.hostname}:8768`,
  timeout: 30000,
});

// Gateway
export const getHealth = () => api.get('/api/health').then(r => r.data);
export const getNodes = () => api.get('/api/nodes').then(r => r.data);

// Blockchain
export const getBlockchainSummary = () => api.get('/api/blockchain/summary').then(r => r.data);
export const getBlocks = (count = 20) => api.get(`/api/blockchain/blocks?count=${count}`).then(r => r.data);
export const getTransactions = (block) => api.get(`/api/blockchain/transactions?block=${block}`).then(r => r.data);

// Tasks
export const getTaskQueue = () => api.get('/api/tasks/queue').then(r => r.data);
export const getTaskHistory = (limit = 100) => api.get(`/api/tasks/history?limit=${limit}`).then(r => r.data);
export const submitTask = (description, priority = 'P2') => api.post('/api/tasks/submit', { description, priority }).then(r => r.data);

// Knowledge
export const getCollections = () => api.get('/api/knowledge/collections').then(r => r.data);
export const searchKnowledge = (collection, query, n = 5) => api.post('/api/knowledge/search', { collection, query, n }).then(r => r.data);

// Agents
export const getAgentStatus = () => api.get('/api/agents/status').then(r => r.data);

// Git
export const getGitLog = (count = 30) => api.get(`/api/git/log?count=${count}`).then(r => r.data);
export const getGitDiff = (hash) => api.get(`/api/git/diff/${hash}`).then(r => r.data);
export const getGitBranches = () => api.get('/api/git/branches').then(r => r.data);

// Tokens
export const getTokenCosts = () => api.get('/api/tokens/costs').then(r => r.data);
export const getTokenActivity = () => api.get('/api/tokens/activity').then(r => r.data);
export const getTokenSummary = () => api.get('/api/tokens/summary').then(r => r.data);

// Logs
export const getLogs = (service, lines = 100) => api.get(`/api/logs/${service}?lines=${lines}`).then(r => r.data);
export const searchLogs = (service, query, lines = 200) => api.post('/api/logs/search', { service, query, lines }).then(r => r.data);

// Health
export const getHealthTimeline = () => api.get('/api/health/timeline').then(r => r.data);
export const getServiceHealth = () => api.get('/api/health/services').then(r => r.data);

// Terminal
export const execTerminalCommand = (command) => api.post('/api/terminal/exec', { command }).then(r => r.data);

// Training
export const getTrainingStats    = () => api.get('/api/training/stats').then(r => r.data);
export const logTrainingSession  = (data) => api.post('/api/training/log', data).then(r => r.data);
export const exportTrainingPairs = () => api.get('/api/training/export/pairs', { responseType: 'blob' }).then(r => r.data);
