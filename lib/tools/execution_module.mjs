// Optional provider-scoped observations, not another durable result service.
import {tool} from '../runtime/schema.mjs';

export function createExecutionModule({coordinator, providers} = {}) {
  const names = Object.keys(providers ?? {});
  if (!coordinator || !names.length || names.some(name => !['image', 'structure'].includes(name))) throw new TypeError('Execution observations need explicitly enabled scientific providers');
  const configured = structuredClone(providers);
  const provider = {type:'string', enum:names};
  const definitions = [
    tool('execution_list', 'Inspect bounded in-memory execution observations for one configured scientific provider. Includes scoped original identity and monotonic queue/start/run/wait/close times. Not a durable scientific result; after restart use image_result or structure_result.',
      {provider, request_id:{type:'string', minLength:1, maxLength:64}, limit:{type:'integer', minimum:1, maximum:100}}, ['provider']),
    tool('execution_info', 'Read one execution observation in the exact configured provider/workspace/session. Does not start a worker or replay an operation; a timeout/failed wait is not proof of scientific failure or rollback.',
      {provider, execution_id:{type:'string', minLength:1, maxLength:100}}, ['provider','execution_id']),
  ];
  return {id:'execution-observer',enabled:true,instructions:'',tools:definitions.map(definition => ({
    definition,
    contract:{backend:'execution-observer',inputs:['ScopedOperationRef:configured provider/workspace/session and optional original request identity'],outputs:['TransientExecutionObservation:timing and wait/lifetime state, not scientific completion'],
      effects:{kind:'inspect',sourceMutation:false,requestId:'none'},gates:['Configured provider scope only; no arbitrary workspace, session or cross-provider lookup'],
      execution:{resourceKeys:[],serialization:'In-memory observation bypasses worker capacity and scientific write resources',budgets:['At most100 observations per call; bounded terminal retention'],cancellation:'No worker or scientific operation is started'},
      recovery:{method:'Inspect only this running Coordinator; query provider original result after restart',tool:null,idField:null,scope:'This Coordinator instance and exact configured provider scope'}},
    execute:args=>{
      const requestScope=configured[args.provider];if(!requestScope)throw new Error('Scientific provider is not configured for observation');
      const value=definition.name==='execution_list'
        ? {observations:coordinator.list({requestScope,requestId:args.request_id,limit:args.limit??50})}
        : {observation:coordinator.inspect(args.execution_id,{requestScope})};
      return {content:[{type:'text',text:JSON.stringify({backend:'execution-observer',state:'completed',...value},null,2)}]};
    },
  }))};
}
