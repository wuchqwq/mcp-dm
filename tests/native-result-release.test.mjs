import test from 'node:test';
import assert from 'node:assert/strict';
import {validateNativeRetention,validateNativeResultAvailability} from '../lib/native_bridge.mjs';

const scope='plugin reference only; shown document may still hold the image; old creation receipt is unchanged';
function result(retained=false) {return {backend:'digitalmicrograph-native',image_id:88,retention_token:3,creation_request_id:'created',plugin_retained:retained,available_for_native_processing:retained,released:!retained,released_now:!retained,result_bytes:24,retained_result_count:retained?1:0,retained_result_bytes:retained?24:0,document_closed:false,source_write_requested:false,native_object_existence:'not_probed',scope};}

test('release/current availability preserve explicit token identity and document boundary',()=>{
  validateNativeResultAvailability(result(),'RELEASE',[88,3]);
  const live=result(true);live.released_now=false;
  validateNativeResultAvailability(live,'RESULT_INFO',[88,3]);
  const prior=result();prior.released_now=false;
  validateNativeResultAvailability(prior,'RESULT_INFO',[88,3]);
  validateNativeResultAvailability(prior,'RELEASE',[88,3]);
});
test('wrong identity, impossible state and document mutation cannot satisfy release',()=>{
  for(const [key,value] of Object.entries({image_id:99,retention_token:4,creation_request_id:'',document_closed:true,source_write_requested:true,native_object_existence:'destroyed',result_bytes:0,retained_result_count:33,retained_result_bytes:16777217,available_for_native_processing:true,plugin_retained:true,released:false})) {
    assert.throws(()=>validateNativeResultAvailability({...result(),[key]:value},'RELEASE',[88,3]),key);
  }
  assert.throws(()=>validateNativeResultAvailability(result(),'RESULT_INFO',[88,3]));
  assert.throws(()=>validateNativeResultAvailability(result(),'RELEASE',[88,0]));
});
test('creation tokens are separate from host IDs and bind their immutable producer',()=>{
  const retention={token:3,creation_request_id:'created',state_at_creation:'plugin_retained',identity_scope:'bridge token in this native session, not a host image ID'};
  validateNativeRetention({retention},'created');validateNativeRetention({},'legacy');
  for(const changed of [{token:0},{token:true},{creation_request_id:'other'},{state_at_creation:'released'},{identity_scope:'host image ID'}])assert.throws(()=>validateNativeRetention({retention:{...retention,...changed}},'created'));
});
