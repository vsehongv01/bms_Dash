import streamlit as st
import inspect

print(f"Streamlit Version: {st.__version__}")

try:
    sig = inspect.signature(st.data_editor)
    print(f"st.data_editor signature: {sig}")
    if 'on_select' in sig.parameters:
        print("on_select is available in st.data_editor")
    else:
        print("on_select is NOT available in st.data_editor")
except Exception as e:
    print(f"Error inspecting data_editor: {e}")

try:
    sig = inspect.signature(st.dataframe)
    print(f"st.dataframe signature: {sig}")
    if 'on_select' in sig.parameters:
        print("on_select is available in st.dataframe")
    else:
        print("on_select is NOT available in st.dataframe")
except Exception as e:
    print(f"Error inspecting dataframe: {e}")
