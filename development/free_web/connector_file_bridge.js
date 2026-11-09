/* Non-terminal connector transport for Windows. Public repository records only.
 * config.cmd must set JRA_RPC_DIRECTORY to config.rpc_directory, a new private
 * scratch directory for each process. No model/history bytes cross this bridge.
 * Run with new Function('tools', source)(tools).run(config).
 */
return {
  async run(config) {
    if (!config.rpc_directory) throw new Error('Unique RPC directory required');
    const node = async code => {
      const raw = await tools.mcp__node_repl__js({code, title:'Verifying GitHub operation'});
      if (raw.isError) throw new Error('File transport failed');
      return (raw.content || []).filter(x=>x.type==='text').map(x=>x.text).join('\n');
    };
    const root = config.rpc_directory.replace(/\\/g,'/');
    const quoted = JSON.stringify;
    await node("var rpcFs=await import('node:fs/promises');");
    let process = await tools.exec_command({cmd:config.cmd,workdir:config.workdir,
      tty:false,yield_time_ms:1000,max_output_tokens:2000});
    const started=Date.now(); let id=1, output=process.output || '';
    while (process.session_id) {
      if (Date.now()-started>(config.timeout_ms || 900000))
        throw new Error('File connector budget exhausted; process has bounded response waits');
      const path=root+'/request-'+id+'.json';
      const request=JSON.parse(await node('nodeRepl.write(await rpcFs.readFile('+quoted(path)+
        ",'utf8').catch(e=>e.code==='ENOENT'?'null':Promise.reject(e)));"));
      if (!request) {
        process=await tools.write_stdin({session_id:process.session_id,chars:'',yield_time_ms:1000,max_output_tokens:2000});
        output+=process.output || ''; continue;
      }
      if (request.id!==id || !['fetch','fetch_file','fetch_commit','create_file'].includes(request.method))
        throw new Error('Invalid connector request');
      const args=request.args;
      if (request.method==='fetch') {
        if (!args.url.startsWith('https://api.github.com/repos/odds-yugami-lab/odds-yugami-lab/'))
          throw new Error('Public repository scope required');
      } else if ((args.repository_full_name || args.repo_full_name)!=='odds-yugami-lab/odds-yugami-lab')
        throw new Error('Public repository scope required');
      let response;
      try {
        const raw=await tools['mcp__codex_apps__github_'+request.method](args);
        if (raw.isError) throw new Error(JSON.stringify(raw.structuredContent || raw.content));
        const value=raw.structuredContent;
        if (!value) throw new Error('Structured connector response missing');
        if (request.method==='fetch' && value.content) {
          const tree=JSON.parse(value.content);
          // snapshot uses only complete path/type membership. Preserve every
          // entry and the server's truncated flag; never synthesize absence.
          if (tree.tree) {tree.tree=tree.tree.map(x=>({path:x.path,type:x.type}));value.content=JSON.stringify(tree);}
        }
        response={id,result:value};
      } catch(error) {response={id,error:String(error).slice(0,2000)};}
      const body=JSON.stringify(response), temporary=root+'/response-'+id+'.json.tmp';
      // Small data-only writes fit the host's per-action review size limit.
      for(let offset=0;offset<body.length;offset+=8000)
        await node('await rpcFs.'+(offset===0?'writeFile':'appendFile')+'('+quoted(temporary)+','+
          quoted(body.slice(offset,offset+8000))+",'utf8');");
      await node('await rpcFs.rename('+quoted(temporary)+','+quoted(root+'/response-'+id+'.json')+');');
      id++;
    }
    if (process.exit_code!==0 || !output.includes('JRA_DONE '))
      throw new Error('Operation did not complete: '+output.slice(-2000));
    return {completed:true,requests:id-1,output};
  }
};
