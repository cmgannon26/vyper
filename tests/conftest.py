import pytest

# from functools import wraps

from eth_tester import (
    EthereumTester,
)
from eth_tester.exceptions import (
    TransactionFailed
)
from web3.providers.eth_tester import (
    EthereumTesterProvider,
)

from web3 import (
    Web3,
)
from web3.contract import (
    ConciseContract,
    ConciseMethod
)
from vyper.parser.parser_utils import (
    LLLnode
)
from vyper import (
    compile_lll,
    compiler,
    optimizer,
)
from vyper.utils import (
    sha3
)


# class VyperMethod(ConciseMethod):

#     def __call__(self, *args, **kwargs):
#         ret = super().__call__(*args, **kwargs)
#         return ret

# class VyperContract(ConciseContract):

#     def __init__(self, classic_contract, method_class=VyperMethod):
#         super().__init__(classic_contract, method_class=method_class)


@pytest.fixture(scope="module")
def tester():
    t = EthereumTester()
    return t


@pytest.fixture(scope="module")
def w3(tester):
    w3 = Web3(EthereumTesterProvider(tester))
    return w3


@pytest.fixture
def check_gas(chain):
    def check_gas(code, func=None, num_txs=1):
        if func:
            gas_estimate = tester.languages['vyper'].gas_estimate(code)[func]
        else:
            gas_estimate = sum(tester.languages['vyper'].gas_estimate(code).values())
        gas_actual = chain.head_state.receipts[-1].gas_used \
                     - chain.head_state.receipts[-1 - num_txs].gas_used \
                     - chain.last_tx.intrinsic_gas_used * num_txs

        # Computed upper bound on the gas consumption should
        # be greater than or equal to the amount of gas used
        if gas_estimate < gas_actual:
            raise Exception("Gas upper bound fail: bound %d actual %d" % (gas_estimate, gas_actual))

        print('Function name: {} - Gas estimate {}, Actual: {}'.format(
            func, gas_estimate, gas_actual)
        )
    return check_gas


def gas_estimation_decorator(chain, fn, source_code, func):
    def decorator(*args, **kwargs):
        @wraps(fn)
        def decorated_function(*args, **kwargs):
            result = fn(*args, **kwargs)
            check_gas(chain)(source_code, func)
            return result
        return decorated_function(*args, **kwargs)
    return decorator


def set_decorator_to_contract_function(chain, contract, source_code, func):
    func_definition = getattr(contract, func)
    func_with_decorator = gas_estimation_decorator(
        chain, func_definition, source_code, func
    )
    setattr(contract, func, func_with_decorator)


@pytest.fixture
def bytes_helper():
    def bytes_helper(str, length):
        return bytes(str, 'utf-8') + bytearray(length - len(str))
    return bytes_helper

@pytest.fixture(scope="module")
def chain():
    tester.languages['vyper'] = compiler.Compiler()
    s = tester.Chain()
    s.head_state.gas_limit = 10**9
    return s


@pytest.fixture
def sha3():
    return Web3.sha3


@pytest.fixture
def get_contract_from_lll(w3):
    def lll_compiler(lll, *args, **kwargs):
        lll = optimizer.optimize(LLLnode.from_list(lll))
        bytecode = compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll))
        abi = []
        contract = w3.eth.contract(bytecode=bytecode, abi=abi)
        deploy_transaction = {
            'data': contract._encode_constructor_data(args, kwargs)
        }
        tx = w3.eth.sendTransaction(deploy_transaction)
        address = w3.eth.getTransactionReceipt(tx)['contractAddress']
        contract = w3.eth.contract(address, abi=abi, bytecode=bytecode, ContractFactoryClass=ConciseContract)
        return contract
    return lll_compiler

def _get_contract(w3, source_code, *args, **kwargs):
    abi = compiler.mk_full_signature(source_code)
    bytecode = '0x' + compiler.compile(source_code).hex()
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    deploy_transaction = {
        'data': contract._encode_constructor_data(args, kwargs)
    }
    tx = w3.eth.sendTransaction(deploy_transaction)
    address = w3.eth.getTransactionReceipt(tx)['contractAddress']
    contract = w3.eth.contract(address, abi=abi, bytecode=bytecode, ContractFactoryClass=ConciseContract)
    return contract

@pytest.fixture
def get_contract(w3):
    def get_contract(source_code, *args, **kwargs):
        return _get_contract(w3, source_code, *args, **kwargs)
    return get_contract


@pytest.fixture
def get_contract_with_gas_estimation(w3):
    def get_contract_with_gas_estimation(source_code, *args, **kwargs):
        return _get_contract(w3, source_code, *args, **kwargs)

    return get_contract_with_gas_estimation


@pytest.fixture
def get_contract_with_gas_estimation_for_constants(w3):
    def get_contract_with_gas_estimation_for_constants(
            source_code,
            *args, **kwargs):
        return _get_contract(w3, source_code, *args, **kwargs)
    return get_contract_with_gas_estimation_for_constants


@pytest.fixture
def assert_tx_failed(tester):
    def assert_tx_failed(function_to_test, exception=TransactionFailed):
        snapshot_id = tester.take_snapshot()
        with pytest.raises(exception):
            function_to_test()
        tester.revert_to_snapshot(snapshot_id)
    return assert_tx_failed


@pytest.fixture
def assert_compile_failed(get_contract_from_lll):
    def assert_compile_failed(function_to_test, exception=Exception):
        with pytest.raises(exception):
            function_to_test()
    return assert_compile_failed


@pytest.fixture
def get_logs():
    def get_logs(receipt, contract, event_name=None):
        contract_log_ids = contract.translator.event_data.keys()  # All the log ids contract has
        # All logs originating from contract, and matching event_name (if specified)
        logs = [log for log in receipt.logs
                if log.topics[0] in contract_log_ids and
                log.address == contract.address and
                (not event_name or
                 contract.translator.event_data[log.topics[0]]['name'] == event_name)]
        assert len(logs) > 0, "No logs in last receipt"

        # Return all events decoded in the receipt
        return [contract.translator.decode_event(log.topics, log.data) for log in logs]
    return get_logs


@pytest.fixture
def get_last_log(get_logs):
    def get_last_log(tester, contract, event_name=None):
        receipt = tester.s.head_state.receipts[-1]  # Only the receipts for the last block
        # Get last log event with correct name and return the decoded event
        print(get_logs(receipt, contract, event_name=event_name))
        return get_logs(receipt, contract, event_name=event_name)[-1]
    return get_last_log
