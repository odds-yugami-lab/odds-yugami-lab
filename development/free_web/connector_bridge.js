/* Execute with new Function('tools', source)(tools), then await bridge.run(...).
 * Uses the existing GitHub connection. It creates no automation and sends no X.
 */
return {
  async run(config) {
    const allowed = new Set(['fetch', 'fetch_file', 'fetch_commit', 'create_file']);
    const unwrap = raw => {
      if (raw.isError) throw new Error(JSON.stringify(raw.content || raw));
      let value = raw.structuredContent;
      if (!value) {
        const blocks = (raw.content || []).filter(x => x.type === 'text');
        value = JSON.parse(blocks.map(x => x.text).join('\n'));
      }
      return value;
    };
    let result = await tools.exec_command({cmd: config.cmd, workdir: config.workdir,
      tty: true, yield_time_ms: 1000, max_output_tokens: 30000});
    let buffer = '', finished = false, seen = new Set();
    const started = Date.now();
    while (true) {
      if ((result.original_token_count || 0) > 30000 || /tokens truncated/.test(result.output))
        throw new Error('RPC output truncated; cannot trust incomplete data');
      buffer += result.output || '';
      let response = null;
      while (buffer.includes('\n')) {
        const end = buffer.indexOf('\n');
        const line = buffer.slice(0, end).replace(/\r$/, '');
        buffer = buffer.slice(end + 1);
        if (line.startsWith('JRA_RPC ')) {
          const rpc = JSON.parse(line.slice(8));
          if (!allowed.has(rpc.method) || seen.has(rpc.id)) throw new Error('Invalid RPC request');
          seen.add(rpc.id);
          try {
            const tool = tools['mcp__codex_apps__github_' + rpc.method];
            if (!tool) throw new Error('GitHub tool unavailable: ' + rpc.method);
            response = {id: rpc.id, result: unwrap(await tool(rpc.args))};
          } catch (error) {
            response = {id: rpc.id, error: String(error).slice(0, 2000)};
          }
        } else if (line.startsWith('JRA_DONE ') || line.startsWith('JRA_FAILED ')) {
          finished = JSON.parse(line.slice(line.indexOf(' ') + 1));
        }
      }
      if (!result.session_id) {
        if (!finished || result.exit_code !== 0)
          throw new Error('Operation did not complete: ' + JSON.stringify(finished || result));
        return finished;
      }
      if (Date.now() - started > (config.timeout_ms || 900000)) {
        await tools.write_stdin({session_id: result.session_id, chars: '\u0003', yield_time_ms: 1000});
        throw new Error('Operation time budget exceeded; no completed delivery');
      }
      result = await tools.write_stdin({session_id: result.session_id,
        chars: response ? JSON.stringify(response) + '\n' : '',
        yield_time_ms: 1000, max_output_tokens: 30000});
    }
  }
};
