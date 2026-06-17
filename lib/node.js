var rpc = require('./jsonrpc');

function Client(opts) {
  this.rpc = new rpc.Client(opts);
};

Client.prototype.cmd = function() {
  var args = [].slice.call(arguments);
  var cmd = args.shift();

  callRpc(cmd, args, this.rpc);
};

function callRpc (cmd, args, rpc) {
  // 取出最後一個參數當 callback（如果有）
  var fn = (typeof args[args.length - 1] === 'function') ? args.pop() : function () {};

  let called = false;                 // 防止重複呼叫
  const done = function () {
    if (called) return;
    called = true;
    fn.apply(this, arguments);
  };

  rpc.call(
    cmd,
    args,
    /* success */ function () {
      const res = Array.from(arguments);
      res.unshift(null);              // 第一個參數放 error = null
      done.apply(this, res);
    },
    /* error   */ function (err) {
      done(err);
    }
  );
}


module.exports.Client = Client;